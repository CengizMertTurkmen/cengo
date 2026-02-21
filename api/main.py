import asyncio
import os
import smtplib
import time
import uuid
from contextlib import asynccontextmanager
from email.mime.text import MIMEText

from dotenv import load_dotenv
import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, Security, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from auth import router as auth_router
from database import init_db, get_account, is_token_expired, get_expiring_accounts
from instagram import InstagramService
from security import require_api_key
from storage import CloudinaryStorage

load_dotenv()

# ── Startup: zorunlu env var'ları kontrol et ─────────────────────────────────
_REQUIRED_ENV_VARS = [
    "API_KEY",
    "CLOUDINARY_CLOUD_NAME",
    "CLOUDINARY_API_KEY",
    "CLOUDINARY_API_SECRET",
    "META_APP_ID",
    "META_APP_SECRET",
    "BASE_URL",
]
_missing = [v for v in _REQUIRED_ENV_VARS if not os.environ.get(v)]
if _missing:
    raise RuntimeError(f"Eksik ortam değişkenleri, uygulama başlatılamıyor: {', '.join(_missing)}")

# ── Swagger: production'da gizle ─────────────────────────────────────────────
_env = os.environ.get("ENV", "development")
_docs_url = None if _env == "production" else "/docs"
_redoc_url = None if _env == "production" else "/redoc"

description = """
## CodEven Instagram İçerik API

Birden fazla Instagram Business hesabına otomatik içerik paylaşımı sağlar.

---

### Nasıl Çalışır?

#### 1. Hesap Bağlama (Bir Kez Yapılır)

Kullanıcının Instagram hesabını sisteme bağlamak için:

1. `POST /auth/link` → `user_id` gönder → tek kullanımlık link al
2. Dönen `url`'yi kullanıcıya gönder
3. Kullanıcı linke tıklar → Instagram ile giriş yapar → hesap otomatik bağlanır

> ⚠️ `/auth/instagram` endpoint'i **Swagger'dan test edilemez**, tarayıcıda açılmalıdır.

---

#### 2. İçerik Paylaşma

Hesap bağlandıktan sonra her post için:

```
POST /api/post
X-Api-Key: {api_key}

form-data:
  user_id = kullanici_id
  image   = resim.jpg
  caption = "Paylaşım metni #hashtag"
```

---

#### 3. Token Yönetimi

Token'lar **60 günde bir** sona erer. Sona ermeden önce yenile:

```
POST /auth/refresh/{user_id}
X-Api-Key: {api_key}
```

Tüm hesapların token durumunu görmek için:
```
GET /auth/accounts
X-Api-Key: {api_key}
```

---

### Kimlik Doğrulama

**Tüm** endpoint'ler için header'da API key gereklidir:
```
X-Api-Key: {api_key}
```
"""

tags_metadata = [
    {
        "name": "Hesap Bağlama",
        "description": "Instagram hesabı bağlama ve token yönetimi (OAuth akışı)",
    },
    {
        "name": "İçerik Paylaşma",
        "description": "Bağlı Instagram hesaplarına fotoğraf paylaşımı",
    },
    {
        "name": "Sistem",
        "description": "API durum kontrolü",
    },
]

# ── Token izleme arkaplan görevi ──────────────────────────────────────────────
_WARN_DAYS = int(os.environ.get("WEBHOOK_DAYS_BEFORE", "7"))


async def _send_expiry_email(accounts: list, now: int):
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    alert_email = os.environ.get("ALERT_EMAIL", "")

    if not all([smtp_host, smtp_user, smtp_pass, alert_email]):
        return

    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    lines = []
    for acc in accounts:
        days_left = max(0, (acc["expires_at"] - now) // 86400)
        if acc["expires_at"] < now:
            status = "SÜRESI DOLMUŞ"
        else:
            status = f"{days_left} gün kaldı"
        lines.append(f"  • {acc['user_id']} (IG: {acc['instagram_user_id']}) — {status}")

    body = (
        f"Merhaba,\n\n"
        f"Aşağıdaki {len(accounts)} Instagram hesabının token'ı "
        f"{_WARN_DAYS} gün içinde sona erecek veya sona ermiş:\n\n"
        + "\n".join(lines)
        + f"\n\nToken yenilemek için:\n  POST /auth/refresh/{{user_id}}\n\n"
        "— CodEven Instagram API"
    )

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"[CodEven] {len(accounts)} hesabın Instagram token'ı sona eriyor"
    msg["From"] = smtp_user
    msg["To"] = alert_email

    def _send():
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)

    await asyncio.to_thread(_send)


async def _notify_expiring_tokens():
    accounts = get_expiring_accounts(_WARN_DAYS)
    if not accounts:
        return
    now = int(time.time())

    # Webhook bildirimi
    webhook_url = os.environ.get("WEBHOOK_URL", "")
    if webhook_url:
        async with httpx.AsyncClient(timeout=10) as client:
            for acc in accounts:
                days_left = max(0, (acc["expires_at"] - now) // 86400)
                try:
                    await client.post(webhook_url, json={
                        "event": "token_expiring",
                        "user_id": acc["user_id"],
                        "instagram_user_id": acc["instagram_user_id"],
                        "expires_in_days": days_left,
                    })
                except Exception:
                    pass

    # E-posta bildirimi
    try:
        await _send_expiry_email(accounts, now)
    except Exception:
        pass


async def _token_check_loop():
    while True:
        try:
            await _notify_expiring_tokens()
        except Exception:
            pass
        await asyncio.sleep(24 * 3600)  # 24 saatte bir kontrol


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(_token_check_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="CodEven Instagram İçerik API",
    version="2.0.0",
    description=description,
    openapi_tags=tags_metadata,
    contact={"name": "CodEven", "email": "admin@codeven.io"},
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# DB başlat
init_db()

# Auth router (OAuth + hesap yönetimi)
app.include_router(auth_router)

# Cloudinary
storage = CloudinaryStorage(
    cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
    api_key=os.environ["CLOUDINARY_API_KEY"],
    api_secret=os.environ["CLOUDINARY_API_SECRET"],
)

MAX_FILE_SIZE = 8 * 1024 * 1024  # 8 MB — Instagram limiti


@app.get("/health", tags=["Sistem"])
def health():
    return {"status": "ok"}


@app.get("/health/tokens", tags=["Sistem"], summary="Token durumu özeti")
def token_health(_=Security(require_api_key)):
    """
    Token'ı sona ermiş veya yakında sona erecek hesapları listeler.

    - Uyarı eşiği `WEBHOOK_DAYS_BEFORE` env var ile ayarlanır (varsayılan: 7 gün)
    - Aynı eşik arkaplan webhook bildirimi için de kullanılır
    """
    now = int(time.time())
    accounts = get_expiring_accounts(_WARN_DAYS)
    return {
        "warning_threshold_days": _WARN_DAYS,
        "total_at_risk": len(accounts),
        "accounts": [
            {
                "user_id": acc["user_id"],
                "instagram_user_id": acc["instagram_user_id"],
                "expires_in_days": max(0, (acc["expires_at"] - now) // 86400),
                "expired": acc["expires_at"] < now,
            }
            for acc in accounts
        ],
    }


@app.post(
    "/api/post",
    tags=["İçerik Paylaşma"],
    status_code=201,
    summary="Instagram'a fotoğraf paylaş",
    response_description="Paylaşım başarılı, Instagram post ID döner",
)
@limiter.limit("10/minute")
async def create_post(
    request: Request,
    _=Security(require_api_key),
    user_id: str = Form(..., description="Kullanıcı ID — `/auth/link` ile hesap bağlarken kullanılan ID"),
    image: UploadFile = File(..., description="Paylaşılacak fotoğraf (JPEG, PNG veya WebP, maks. 8 MB)"),
    caption: str = Form(..., description="Gönderi açıklaması (hashtag ve emoji dahil edilebilir)"),
):
    """
    Belirtilen kullanıcının Instagram Business hesabına fotoğraf paylaşır.

    **Gereksinimler:**
    - Kullanıcının daha önce `/auth/link` → Instagram OAuth akışı ile hesabı bağlamış olması gerekir
    - Header'da geçerli `X-Api-Key` bulunmalıdır

    **Hata Durumları:**
    - `401` → API key hatalı veya token süresi dolmuş (`/auth/refresh/{user_id}` ile yenile)
    - `404` → Bu `user_id` için bağlı hesap bulunamadı
    - `400` → Desteklenmeyen dosya formatı, boş veya çok büyük dosya
    - `429` → Çok fazla istek (maks. 10/dakika)
    - `500` → Cloudinary yükleme veya Instagram API hatası
    """
    # Hesabı DB'den al
    account = get_account(user_id)
    if not account:
        raise HTTPException(
            status_code=404,
            detail=f"'{user_id}' ID'li hesap bulunamadı. Önce /auth/link ile hesabı bağlayın.",
        )

    # Token yakında sona erecek mi?
    if is_token_expired(account):
        raise HTTPException(
            status_code=401,
            detail=f"'{user_id}' hesabının token'ı sona eriyor. /auth/refresh/{user_id} ile yenileyin.",
        )

    if image.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(
            status_code=400,
            detail="Sadece JPEG, PNG veya WebP dosyaları kabul edilir.",
        )

    file_bytes = await image.read()

    if not file_bytes:
        raise HTTPException(status_code=400, detail="Dosya boş.")

    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Dosya boyutu çok büyük. Maksimum {MAX_FILE_SIZE // (1024 * 1024)} MB yüklenebilir.",
        )

    # 1. Cloudinary'e yükle → public URL al
    public_id = f"codeven/{uuid.uuid4().hex}"
    try:
        image_url = storage.upload(file_bytes, public_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fotoğraf yüklenemedi: {e}")

    # 2. Instagram'da paylaş
    instagram = InstagramService(
        user_id=account["instagram_user_id"],
        access_token=account["access_token"],
    )
    try:
        result = await instagram.post_image(image_url=image_url, caption=caption)
    except Exception as e:
        try:
            storage.delete(public_id)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Instagram paylaşımı başarısız: {e}")

    return JSONResponse(
        status_code=201,
        content={
            "success": True,
            "instagram_post_id": result.get("id"),
            "image_url": image_url,
        },
    )
