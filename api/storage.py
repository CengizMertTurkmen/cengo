import cloudinary
import cloudinary.uploader


class CloudinaryStorage:
    def __init__(self, cloud_name: str, api_key: str, api_secret: str):
        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
        )

    def upload(self, file_bytes: bytes, filename: str) -> str:
        """Fotoğrafı Cloudinary'e yükler, public URL döner."""
        result = cloudinary.uploader.upload(
            file_bytes,
            public_id=filename,
            overwrite=True,
            resource_type="image",
        )
        return result["secure_url"]

    def upload_video(self, file_bytes: bytes, filename: str) -> str:
        """Videoyu Cloudinary'e yükler, public URL döner."""
        result = cloudinary.uploader.upload(
            file_bytes,
            public_id=filename,
            overwrite=True,
            resource_type="video",
        )
        return result["secure_url"]

    def delete(self, public_id: str, resource_type: str = "image") -> None:
        cloudinary.uploader.destroy(public_id, resource_type=resource_type)
