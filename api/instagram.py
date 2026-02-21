import asyncio
import httpx

GRAPH_API = "https://graph.instagram.com/v21.0"
_POLL_INTERVAL = 3   # saniye
_POLL_ATTEMPTS = 20  # max 60 saniye


class InstagramService:
    def __init__(self, user_id: str, access_token: str):
        self.user_id = user_id
        self.access_token = access_token

    # ------------------------------------------------------------------ helpers

    async def _wait_until_ready(self, client: httpx.AsyncClient, creation_id: str) -> None:
        """Container FINISHED olana kadar yokla, ERROR veya timeout'ta exception fırlat."""
        for _ in range(_POLL_ATTEMPTS):
            res = await client.get(
                f"{GRAPH_API}/{creation_id}",
                params={"fields": "status_code", "access_token": self.access_token},
            )
            if res.status_code == 200:
                status = res.json().get("status_code")
                if status == "FINISHED":
                    return
                if status == "ERROR":
                    raise Exception("Media container hazırlanırken Instagram API hatası oluştu.")
            await asyncio.sleep(_POLL_INTERVAL)
        raise Exception("Media container zaman aşımına uğradı (60 sn).")

    async def _publish(self, client: httpx.AsyncClient, creation_id: str) -> dict:
        """Container'ı yayınlar, sonucu döner."""
        res = await client.post(
            f"{GRAPH_API}/{self.user_id}/media_publish",
            params={"creation_id": creation_id, "access_token": self.access_token},
        )
        if res.status_code != 200:
            raise Exception(f"Yayınlama başarısız: {res.text}")
        return res.json()

    # ------------------------------------------------------------------ public API

    async def post_image(self, image_url: str, caption: str) -> dict:
        """Tekli fotoğraf paylaşır."""
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                f"{GRAPH_API}/{self.user_id}/media",
                params={
                    "image_url": image_url,
                    "caption": caption,
                    "access_token": self.access_token,
                },
            )
            if res.status_code != 200:
                raise Exception(f"Container oluşturulamadı: {res.text}")
            creation_id = res.json()["id"]
            await self._wait_until_ready(client, creation_id)
            return await self._publish(client, creation_id)

    async def post_reel(self, video_url: str, caption: str, cover_url: str = None) -> dict:
        """
        Reels videosu paylaşır.
        1. Container oluştur (media_type=REELS) → 2. FINISHED bekle → 3. Yayınla
        """
        params = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true",
            "access_token": self.access_token,
        }
        if cover_url:
            params["cover_url"] = cover_url

        async with httpx.AsyncClient(timeout=60) as client:
            res = await client.post(f"{GRAPH_API}/{self.user_id}/media", params=params)
            if res.status_code != 200:
                raise Exception(f"Reel container oluşturulamadı: {res.text}")
            creation_id = res.json()["id"]
            await self._wait_until_ready(client, creation_id)
            return await self._publish(client, creation_id)

    async def post_carousel(self, image_urls: list[str], caption: str) -> dict:
        """
        Carousel (2–10 fotoğraf) paylaşır.
        1. Her fotoğraf için child container oluştur
        2. Carousel container oluştur (media_type=CAROUSEL)
        3. FINISHED bekle → 4. Yayınla
        """
        async with httpx.AsyncClient(timeout=60) as client:
            # Adım 1: child container'lar
            child_ids = []
            for url in image_urls:
                res = await client.post(
                    f"{GRAPH_API}/{self.user_id}/media",
                    params={
                        "image_url": url,
                        "is_carousel_item": "true",
                        "access_token": self.access_token,
                    },
                )
                if res.status_code != 200:
                    raise Exception(f"Child container oluşturulamadı: {res.text}")
                child_ids.append(res.json()["id"])

            # Adım 2: carousel container
            res = await client.post(
                f"{GRAPH_API}/{self.user_id}/media",
                params={
                    "media_type": "CAROUSEL",
                    "children": ",".join(child_ids),
                    "caption": caption,
                    "access_token": self.access_token,
                },
            )
            if res.status_code != 200:
                raise Exception(f"Carousel container oluşturulamadı: {res.text}")
            creation_id = res.json()["id"]
            await self._wait_until_ready(client, creation_id)
            return await self._publish(client, creation_id)

    async def post_story(self, media_url: str, is_video: bool = False) -> dict:
        """
        Story paylaşır (fotoğraf veya video).
        1. Container oluştur (media_type=STORIES) → 2. Yayınla
        """
        param_key = "video_url" if is_video else "image_url"
        async with httpx.AsyncClient(timeout=60) as client:
            res = await client.post(
                f"{GRAPH_API}/{self.user_id}/media",
                params={
                    "media_type": "STORIES",
                    param_key: media_url,
                    "access_token": self.access_token,
                },
            )
            if res.status_code != 200:
                raise Exception(f"Story container oluşturulamadı: {res.text}")
            creation_id = res.json()["id"]
            if is_video:
                await self._wait_until_ready(client, creation_id)
            return await self._publish(client, creation_id)
