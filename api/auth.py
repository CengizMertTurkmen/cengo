import os
import time

import httpx
from fastapi import APIRouter, HTTPException, Security
from fastapi.responses import HTMLResponse, RedirectResponse

from database import save_account, list_accounts, is_token_expired, get_account, delete_account, create_auth_token, consume_auth_token
from security import require_api_key

router = APIRouter(prefix="/auth", tags=["Hesap Bağlama"])

IG_OAUTH_URL = "https://www.instagram.com/oauth/authorize"
IG_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
IG_LONGTOKEN_URL = "https://graph.instagram.com/access_token"
SCOPES = "instagram_business_basic,instagram_business_content_publish"


@router.post("/link", summary="Hesap bağlama linki üret")
def create_auth_link(user_id: str, _=Security(require_api_key)):
    """
    Tek kullanımlık Instagram bağlama linki üretir.

    - **user_id**: Kendi sistemindeki kullanıcı adı veya ID (örn: `mert`, `user_42`)

    **Kullanım:**
    1. Bu endpoint'i çağır → `url` al
    2. O URL'yi **tarayıcıda aç** (Swagger'dan değil!) → Instagram login sayfası açılır
    3. Kullanıcı izin verince hesap otomatik bağlanır

    > Link 24 saat geçerlidir ve tek kullanımlıktır.
    """
    base_url = os.environ["BASE_URL"].rstrip("/")
    token = create_auth_token(user_id)
    return {
        "url": f"{base_url}/auth/instagram?token={token}",
        "expires_in_hours": 24,
    }


@router.get("/instagram", summary="Instagram OAuth yönlendirmesi (tarayıcıda açılır)", include_in_schema=True)
def instagram_login(token: str):
    """
    Instagram OAuth sayfasına yönlendirir.

    > ⚠️ **Bu endpoint Swagger'dan test edilemez.** Tarayıcıdan açılmalıdır.
    >
    > Önce `POST /auth/link` ile link al, dönen `url`'yi tarayıcı adres çubuğuna yapıştır.

    - **token**: `/auth/link` endpoint'inden alınan tek kullanımlık token
    """
    app_id = os.environ["META_APP_ID"]
    base_url = os.environ["BASE_URL"].rstrip("/")
    redirect_uri = f"{base_url}/auth/callback"

    url = (
        f"{IG_OAUTH_URL}"
        f"?client_id={app_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={SCOPES}"
        f"&response_type=code"
        f"&state={token}"
    )
    return RedirectResponse(url)


@router.get("/callback")
async def instagram_callback(code: str = None, state: str = None, error: str = None):
    """
    Instagram OAuth callback.
    Token alır, long-lived token'a çevirir ve DB'ye kaydeder.
    """
    if error:
        raise HTTPException(status_code=400, detail=f"Kullanıcı izin vermedi: {error}")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Geçersiz callback parametreleri.")

    user_id = consume_auth_token(state)
    if user_id is None:
        raise HTTPException(status_code=400, detail="Geçersiz veya süresi dolmuş link. Yeni bir link talep edin.")
    app_id = os.environ["META_APP_ID"]
    app_secret = os.environ["META_APP_SECRET"]
    base_url = os.environ["BASE_URL"].rstrip("/")
    redirect_uri = f"{base_url}/auth/callback"

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Code → short-lived token
        token_res = await client.post(
            IG_TOKEN_URL,
            data={
                "client_id": app_id,
                "client_secret": app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        if token_res.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Token alınamadı: {token_res.text}")

        token_data = token_res.json()
        short_token = token_data["access_token"]
        instagram_user_id = str(token_data["user_id"])

        # 2. Short-lived → long-lived token (60 gün)
        ll_res = await client.get(
            IG_LONGTOKEN_URL,
            params={
                "grant_type": "ig_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "access_token": short_token,
            },
        )
        if ll_res.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Long-lived token alınamadı: {ll_res.text}")

        ll_data = ll_res.json()
        long_token = ll_data["access_token"]
        expires_in = ll_data.get("expires_in", 5184000)

    expires_at = int(time.time()) + expires_in
    save_account(user_id, instagram_user_id, long_token, expires_at)

    expires_days = expires_in // 86400
    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Hesap Bağlandı</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #f0f2f5;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
    }}
    .card {{
      background: #fff;
      border-radius: 16px;
      padding: 48px 40px;
      max-width: 420px;
      width: 100%;
      text-align: center;
      box-shadow: 0 4px 24px rgba(0,0,0,0.08);
    }}
    .icon {{ font-size: 56px; margin-bottom: 20px; }}
    h1 {{ font-size: 22px; color: #1a1a1a; margin-bottom: 10px; }}
    p {{ color: #666; font-size: 15px; line-height: 1.6; }}
    .badge {{
      display: inline-block;
      margin-top: 24px;
      background: #f0fdf4;
      color: #16a34a;
      border: 1px solid #bbf7d0;
      border-radius: 8px;
      padding: 10px 20px;
      font-size: 14px;
      font-weight: 500;
    }}
    .meta {{ margin-top: 32px; font-size: 12px; color: #aaa; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">✅</div>
    <h1>Instagram Hesabı Bağlandı</h1>
    <p>Hesabın başarıyla sisteme bağlandı.<br>Bu sekmeyi kapatabilirsin.</p>
    <div class="badge">Token {expires_days} gün geçerli</div>
    <div class="meta">user_id: {user_id} &nbsp;·&nbsp; ig: {instagram_user_id}</div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/accounts", summary="Bağlı tüm hesapları listele")
def get_accounts(_=Security(require_api_key)):
    """Sistemde kayıtlı tüm Instagram hesaplarını ve token durumlarını listeler."""
    accounts = list_accounts()
    now = int(time.time())
    return [
        {
            **acc,
            "token_expires_in_days": max(0, (acc["expires_at"] - now) // 86400) if acc.get("expires_at") else None,
            "token_warning": is_token_expired(acc),
        }
        for acc in accounts
    ]


@router.get("/accounts/{user_id}", summary="Tek hesabı sorgula")
def get_account_detail(user_id: str, _=Security(require_api_key)):
    """Belirtilen `user_id`'ye ait hesabın bilgilerini ve token durumunu döner."""
    account = get_account(user_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"'{user_id}' bulunamadı.")
    now = int(time.time())
    expires_at = account.get("expires_at")
    return {
        "user_id": account["user_id"],
        "instagram_user_id": account["instagram_user_id"],
        "token_expires_in_days": max(0, (expires_at - now) // 86400) if expires_at else None,
        "token_warning": is_token_expired(account),
    }


@router.delete("/accounts/{user_id}", summary="Hesabı sil", status_code=200)
def remove_account(user_id: str, _=Security(require_api_key)):
    """Belirtilen `user_id`'ye ait hesabı sistemden kalıcı olarak siler."""
    deleted = delete_account(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"'{user_id}' bulunamadı.")
    return {"success": True, "message": f"'{user_id}' hesabı silindi."}


@router.post("/refresh/{user_id}", summary="Token yenile (60 günde bir)")
async def refresh_token(user_id: str, _=Security(require_api_key)):
    """
    Hesabın Instagram token'ını yeniler.

    - Token'lar **60 günde bir** sona erer
    - Sona ermeden **en az 1 hafta önce** çağırmanız önerilir
    - `GET /auth/accounts` ile token sürelerini takip edebilirsiniz
    """
    account = get_account(user_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"'{user_id}' bulunamadı.")

    app_id = os.environ["META_APP_ID"]
    app_secret = os.environ["META_APP_SECRET"]

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(
            "https://graph.instagram.com/refresh_access_token",
            params={
                "grant_type": "ig_refresh_token",
                "access_token": account["access_token"],
            },
        )
        if res.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Token yenilenemedi: {res.text}")

        data = res.json()
        new_token = data["access_token"]
        expires_in = data.get("expires_in", 5184000)

    expires_at = int(time.time()) + expires_in
    save_account(user_id, account["instagram_user_id"], new_token, expires_at)

    return {
        "success": True,
        "message": "Token yenilendi.",
        "token_expires_days": expires_in // 86400,
    }
