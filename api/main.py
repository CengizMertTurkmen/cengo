import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from auth import router as auth_router
from database import init_db, get_account, is_token_expired
from instagram import InstagramService
from storage import CloudinaryStorage

load_dotenv()

app = FastAPI(title="Cengo Content API", version="2.0.0")

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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/post")
async def create_post(
    user_id: str = Form(..., description="Müşteri ID (kayıt sırasında verilen)"),
    image: UploadFile = File(..., description="Paylaşılacak fotoğraf"),
    caption: str = Form(..., description="Fotoğraf altı yazı"),
):
    """
    Belirtilen kullanıcının Instagram hesabına fotoğraf paylaşır.

    - **user_id**: Hesap bağlama sırasında kullanılan müşteri ID
    - **image**: JPEG veya PNG fotoğraf dosyası
    - **caption**: Gönderi açıklaması (hashtag'ler dahil)
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
    public_id = f"cengo/{uuid.uuid4().hex}"
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
