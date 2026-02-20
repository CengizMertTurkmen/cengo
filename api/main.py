import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Security, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader

from auth import router as auth_router
from database import init_db, get_account, is_token_expired
from instagram import InstagramService
from storage import CloudinaryStorage

load_dotenv()

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
```

Tüm hesapların token durumunu görmek için:
```
GET /auth/accounts
```

---

### Kimlik Doğrulama

`/api/post` endpoint'i için header'da API key gereklidir:
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

app = FastAPI(
    title="CodEven Instagram İçerik API",
    version="2.0.0",
    description=description,
    openapi_tags=tags_metadata,
    contact={"name": "CodEven", "email": "admin@codeven.io"},
)

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

# API Key doğrulama
_api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)


def require_api_key(key: str = Security(_api_key_header)):
    expected = os.environ.get("API_KEY", "")
    if not expected:
        raise HTTPException(status_code=500, detail="Sunucuda API_KEY tanımlı değil.")
    if key != expected:
        raise HTTPException(status_code=401, detail="Geçersiz veya eksik API key.")


@app.get("/health", tags=["Sistem"])
def health():
    return {"status": "ok"}


@app.post(
    "/api/post",
    tags=["İçerik Paylaşma"],
    status_code=201,
    summary="Instagram'a fotoğraf paylaş",
    response_description="Paylaşım başarılı, Instagram post ID döner",
)
async def create_post(
    _=Security(require_api_key),
    user_id: str = Form(..., description="Kullanıcı ID — `/auth/link` ile hesap bağlarken kullanılan ID"),
    image: UploadFile = File(..., description="Paylaşılacak fotoğraf (JPEG, PNG veya WebP)"),
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
    - `400` → Desteklenmeyen dosya formatı veya boş dosya
    - `500` → Cloudinary yükleme veya Instagram API hatası
    """
    # Hesabı DB'den al
    account = get_account(user_id)
    if not account:
        raise HTTPException(
            status_code=404,
            detail=f"'{user_id}' ID'li hesap bulunamadı. Önce /auth/instagram?user_id={user_id} ile hesabı bağlayın.",
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
