import os
import time

import httpx
from fastapi import APIRouter, HTTPException, Security
from fastapi.responses import RedirectResponse

from database import save_account, list_accounts, is_token_expired, get_account, create_auth_token, consume_auth_token
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

    return {
        "success": True,
        "message": "Instagram hesabı başarıyla bağlandı.",
        "user_id": user_id,
        "instagram_user_id": instagram_user_id,
        "token_expires_days": expires_in // 86400,
    }


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
