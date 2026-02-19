import os
import time

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from database import save_account, list_accounts, is_token_expired, get_account

router = APIRouter(prefix="/auth", tags=["auth"])

GRAPH_API = "https://graph.facebook.com/v21.0"
FB_OAUTH_URL = "https://www.facebook.com/v21.0/dialog/oauth"
SCOPES = "instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement"


@router.get("/instagram")
def instagram_login(user_id: str):
    """
    Kullanıcıyı Instagram OAuth sayfasına yönlendir.
    Müşteri bu linki kendi müşterilerine gönderir:
      GET /auth/instagram?user_id=MUSTERI_ID
    """
    app_id = os.environ["META_APP_ID"]
    base_url = os.environ["BASE_URL"].rstrip("/")
    redirect_uri = f"{base_url}/auth/callback"

    url = (
        f"{FB_OAUTH_URL}"
        f"?client_id={app_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={SCOPES}"
        f"&response_type=code"
        f"&state={user_id}"
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

    user_id = state
    app_id = os.environ["META_APP_ID"]
    app_secret = os.environ["META_APP_SECRET"]
    base_url = os.environ["BASE_URL"].rstrip("/")
    redirect_uri = f"{base_url}/auth/callback"

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Code → short-lived user token
        token_res = await client.get(
            f"{GRAPH_API}/oauth/access_token",
            params={
                "client_id": app_id,
                "client_secret": app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        if token_res.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Token alınamadı: {token_res.text}")
        short_token = token_res.json()["access_token"]

        # 2. Short-lived → long-lived token (60 gün)
        ll_res = await client.get(
            f"{GRAPH_API}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": short_token,
            },
        )
        if ll_res.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Long-lived token alınamadı: {ll_res.text}")
        ll_data = ll_res.json()
        long_token = ll_data["access_token"]
        expires_in = ll_data.get("expires_in", 5184000)  # default 60 gün

        # 3. Facebook Page listesini al
        pages_res = await client.get(
            f"{GRAPH_API}/me/accounts",
            params={"access_token": long_token},
        )
        if pages_res.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Sayfalar alınamadı: {pages_res.text}")
        pages = pages_res.json().get("data", [])

        if not pages:
            raise HTTPException(
                status_code=400,
                detail="Facebook Sayfası bulunamadı. Instagram hesabınızı bir Facebook Sayfasına bağlayın.",
            )

        # 4. Instagram Business Account ID al (ilk sayfayı kullan)
        page = pages[0]
        page_id = page["id"]
        page_token = page["access_token"]

        ig_res = await client.get(
            f"{GRAPH_API}/{page_id}",
            params={
                "fields": "instagram_business_account",
                "access_token": page_token,
            },
        )
        if ig_res.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Instagram hesabı alınamadı: {ig_res.text}")
        ig_data = ig_res.json()

        if "instagram_business_account" not in ig_data:
            raise HTTPException(
                status_code=400,
                detail="Bu Facebook Sayfasına bağlı Instagram Business/Creator hesabı yok.",
            )

        instagram_user_id = ig_data["instagram_business_account"]["id"]

    expires_at = int(time.time()) + expires_in
    save_account(user_id, instagram_user_id, long_token, expires_at)

    return {
        "success": True,
        "message": "Instagram hesabı başarıyla bağlandı.",
        "user_id": user_id,
        "instagram_user_id": instagram_user_id,
        "token_expires_days": expires_in // 86400,
    }


@router.get("/accounts")
def get_accounts():
    """Kayıtlı tüm hesapları listele."""
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


@router.post("/refresh/{user_id}")
async def refresh_token(user_id: str):
    """
    Hesabın token'ını yenile (60 günden önce çağırılmalı).
    Token süresi dolmadan yenilenebilir.
    """
    account = get_account(user_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"'{user_id}' bulunamadı.")

    app_id = os.environ["META_APP_ID"]
    app_secret = os.environ["META_APP_SECRET"]

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(
            f"{GRAPH_API}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": account["access_token"],
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
