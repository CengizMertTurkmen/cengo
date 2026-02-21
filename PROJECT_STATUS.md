# PROJECT STATUS — CodEven Instagram API

**Son güncelleme:** 21 Şubat 2026
**Aktif branch:** `claude/create-content-api-3uDwo`
**Son commit:** `ad4c59c` — Reel, Carousel ve Story paylaşma endpoint'leri eklendi

---

## Mevcut Endpointler (Tam Liste)

### Kimlik Doğrulama (`/auth`) — `auth.py`
| Method | Path | Açıklama |
|--------|------|----------|
| POST | `/auth/link` | Hesap bağlama için tek kullanımlık link üret |
| GET | `/auth/instagram` | Instagram OAuth yönlendirmesi (tarayıcıda açılır) |
| GET | `/auth/callback` | OAuth callback — token alır, DB'ye kaydeder |
| GET | `/auth/accounts` | Bağlı tüm hesapları listele |
| GET | `/auth/accounts/{user_id}` | Tek hesabı sorgula |
| DELETE | `/auth/accounts/{user_id}` | Hesabı sil |
| POST | `/auth/refresh/{user_id}` | Token yenile (60 günde bir gerekir) |

### İçerik Paylaşma — `main.py`
| Method | Path | Açıklama | Format | Limit |
|--------|------|----------|--------|-------|
| POST | `/api/post` | Tekli fotoğraf paylaş | JPEG/PNG/WebP, maks 8 MB | 10/dk |
| POST | `/api/reel` | Reels videosu paylaş | MP4/MOV, maks 100 MB | 5/dk |
| POST | `/api/carousel` | 2–10 fotoğraf carousel | JPEG/PNG/WebP, her biri maks 8 MB | 5/dk |
| POST | `/api/story` | Fotoğraf veya video story | JPEG/PNG/WebP/MP4/MOV | 10/dk |

### Sistem — `main.py`
| Method | Path | Açıklama |
|--------|------|----------|
| GET | `/health` | API ayakta mı |
| GET | `/health/tokens` | Tüm hesapların token durumu |

---

## Dosyaların Mevcut Durumu

### `main.py`
- Tüm içerik paylaşma endpointleri burada
- `MAX_FILE_SIZE = 8 MB`, `MAX_VIDEO_SIZE = 100 MB`
- `_IMAGE_TYPES`, `_VIDEO_TYPES` sabitleri var
- Token izleme arkaplan görevi: günde bir çalışır, WEBHOOK_URL veya SMTP ile bildirim gönderir
- Zorunlu env var'lar başlangıçta kontrol edilir

### `instagram.py`
- `InstagramService` sınıfı
- `_wait_until_ready()` — container FINISHED olana kadar yoklar (max 60 sn)
- `_publish()` — container'ı yayınlar
- `post_image(image_url, caption)`
- `post_reel(video_url, caption, cover_url=None)`
- `post_carousel(image_urls, caption)`
- `post_story(media_url, is_video=False)`

### `storage.py`
- `upload(file_bytes, filename)` — fotoğraf yükle → URL döner
- `upload_video(file_bytes, filename)` — video yükle → URL döner
- `delete(public_id, resource_type="image")` — sil

### `auth.py`
- Instagram OAuth tam akışı
- Tek kullanımlık auth token sistemi (24 saat geçerli)
- Token yenileme (Instagram long-lived token, 60 gün)

### `database.py`
- SQLite, `/app/data/codeven.db`
- Tablolar: `accounts`, `auth_tokens`

### `security.py`
- `X-Api-Key` header doğrulama
- `slowapi` ile rate limiting

---

## Ortam Değişkenleri

### Zorunlu (eksikse uygulama başlamaz)
```
API_KEY
CLOUDINARY_CLOUD_NAME
CLOUDINARY_API_KEY
CLOUDINARY_API_SECRET
META_APP_ID
META_APP_SECRET
BASE_URL
```

### Opsiyonel
```
ENV=production          # Swagger'ı kapatır (varsayılan: development)
WEBHOOK_DAYS_BEFORE=7   # Kaç gün kala uyarı (varsayılan: 7)
WEBHOOK_URL=...         # Token uyarı webhook'u
SMTP_HOST/PORT/USER/PASS/ALERT_EMAIL  # E-posta bildirimi
```

---

## Server Kurulumu (Tamamlandı)

- `codeven-api` container'ı: `~/cengo/api/` altında, `docker compose up -d` ile çalışır
- Nginx: `kodera-nginx` Docker container'ı (`/opt/kodera-api/`) — 80/443 portlarını yönetir
- Nginx config: `/opt/kodera-api/nginx.conf` → `api.codeven.io` → `172.17.0.1:8000`
- SSL: `/etc/letsencrypt/live/api.codeven.io/` (mevcut sertifika)
- Swagger: `https://api.codeven.io/docs` ✅

### Güncelleme Prosedürü
```bash
cd ~/cengo
git pull origin claude/create-content-api-3uDwo
cd api
docker compose down && docker compose up --build -d
```

### Nginx Config Değişikliği Gerekirse
```bash
# /opt/kodera-api/nginx.conf dosyasını düzenle
# Sonra container'ı yeniden oluştur (reload yetmez — inode sorunu):
cd /opt/kodera-api
docker compose stop nginx && docker compose rm -f nginx && docker compose up -d nginx
```

---

## Tamamlananlar
- [x] Instagram OAuth + hesap bağlama (tek kullanımlık link)
- [x] Tekli fotoğraf paylaşma (`/api/post`)
- [x] Reels video paylaşma (`/api/reel`)
- [x] Carousel paylaşma (`/api/carousel`)
- [x] Story paylaşma (`/api/story`)
- [x] Token izleme + webhook bildirimi
- [x] Token izleme + e-posta bildirimi (SMTP, opsiyonel)
- [x] API key güvenliği
- [x] Rate limiting
- [x] Cloudinary entegrasyonu (fotoğraf + video)
- [x] Health endpointleri
- [x] Swagger UI (development)

## Planlanmış / Yapılmamış
- [ ] Belirsiz — kullanıcıdan yeni görev bekleniyor
