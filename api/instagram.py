import httpx

GRAPH_API = "https://graph.instagram.com/v21.0"


class InstagramService:
    def __init__(self, user_id: str, access_token: str):
        self.user_id = user_id
        self.access_token = access_token

    async def post_image(self, image_url: str, caption: str) -> dict:
        """
        Instagram Graph API ile fotoğraf paylaşır.
        2 adım:
          1. Media container oluştur
          2. Container'ı yayınla
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
            container_res.raise_for_status()
            creation_id = container_res.json()["id"]

            # Adım 2: Yayınla
            publish_res = await client.post(
                f"{GRAPH_API}/{self.user_id}/media_publish",
                params={
                    "creation_id": creation_id,
                    "access_token": self.access_token,
                },
            )
            publish_res.raise_for_status()
            return publish_res.json()
