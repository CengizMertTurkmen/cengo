import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from instagram import InstagramService
from storage import CloudinaryStorage

load_dotenv()

app = FastAPI(title="Cengo Content API", version="1.0.0")

# Servisler
storage = CloudinaryStorage(
    cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
    api_key=os.environ["CLOUDINARY_API_KEY"],
    api_secret=os.environ["CLOUDINARY_API_SECRET"],
)

instagram = InstagramService(
    user_id=os.environ["INSTAGRAM_USER_ID"],
    access_token=os.environ["INSTAGRAM_ACCESS_TOKEN"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/post")
async def create_post(
    image: UploadFile = File(..., description="Paylaşılacak fotoğraf"),
    caption: str = Form(..., description="Fotoğraf altı yazı"),
):
    """
    Müşteriden fotoğraf + yazı alır, Instagram'da paylaşır.

    - **image**: JPEG veya PNG fotoğraf dosyası
    - **caption**: Gönderi açıklaması (hashtag'ler dahil)
    """
    # Sadece resim formatlarını kabul et
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
    try:
        result = await instagram.post_image(image_url=image_url, caption=caption)
    except Exception as e:
        # Yüklenen dosyayı temizle
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
