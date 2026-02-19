import asyncio
import httpx

GRAPH_API = "https://graph.instagram.com/v21.0"


class InstagramService:
    def __init__(self, user_id: str, access_token: str):
        self.user_id = user_id
        self.access_token = access_token

    async def post_image(self, image_url: str, caption: str) -> dict:
        """
        Instagram Graph API ile fotoğraf paylaşır.
        3 adım:
          1. Media container oluştur
          2. Container FINISHED olana kadar bekle
          3. Container'ı yayınla
        """
        async with httpx.AsyncClient(timeout=30) as client:
            # Adım 1: Media container oluştur
            container_res = await client.post(
                f"{GRAPH_API}/{self.user_id}/media",
                params={
                    "image_url": image_url,
                    "caption": caption,
                    "access_token": self.access_token,
                },
            )
            if container_res.status_code != 200:
                raise Exception(f"Container oluşturulamadı: {container_res.text}")
            creation_id = container_res.json()["id"]

            # Adım 2: Container FINISHED olana kadar bekle (max 30 saniye)
            for _ in range(10):
                status_res = await client.get(
                    f"{GRAPH_API}/{creation_id}",
                    params={
                        "fields": "status_code",
                        "access_token": self.access_token,
                    },
                )
                if status_res.status_code == 200:
                    status = status_res.json().get("status_code")
                    if status == "FINISHED":
                        break
                    if status == "ERROR":
                        raise Exception(f"Container hazırlanırken hata oluştu.")
                await asyncio.sleep(3)

            # Adım 3: Yayınla
            publish_res = await client.post(
                f"{GRAPH_API}/{self.user_id}/media_publish",
                params={
                    "creation_id": creation_id,
                    "access_token": self.access_token,
                },
            )
            if publish_res.status_code != 200:
                raise Exception(f"Yayınlama başarısız: {publish_res.text}")
            return publish_res.json()
