# CodEven Instagram API — Claude Kuralları

## Geliştirme Şubesi
Her zaman `claude/create-content-api-3uDwo` dalında çalış. Başka dala push yapma.

## Her Değişiklikten Sonra Zorunlu
Her kod değişikliğinden sonra `PROJECT_STATUS.md` dosyasını güncelle:
- Hangi dosya değiştirildi ve ne yapıldı
- Tüm mevcut endpointlerin güncel listesi
- Planlanmış ama henüz yapılmamış işler
- Server'da yapılması gerekenler (restart, rebuild vs.)
- Önemli notlar / kısıtlamalar

Bu kural, bağlamı sıfırlanan başka bir yapay zekanın projeyi sıfırdan anlayabilmesi içindir.

## Proje Yapısı
```
cengo/
├── api/
│   ├── main.py        — FastAPI app, tüm endpoint'ler
│   ├── instagram.py   — Instagram Graph API servisi
│   ├── auth.py        — OAuth router
│   ├── database.py    — SQLite işlemleri
│   ├── storage.py     — Cloudinary yükleme/silme
│   ├── security.py    — API key doğrulama
│   └── requirements.txt
└── mobil/             — (mobil taraf, dokunma)
```

## Teknoloji Stack
- **FastAPI** + **uvicorn** (Python)
- **SQLite** — hesap ve token veritabanı (`/app/data/codeven.db`)
- **Cloudinary** — medya dosyası barındırma (Instagram için public URL gerektirir)
- **Instagram Graph API v21.0**
- **Docker** — deployment

## Önemli Kurallar
- Zorunlu env var'lar `main.py`'daki `_REQUIRED_ENV_VARS` listesinde; eksikse uygulama başlamaz
- `ENV=production` iken Swagger (`/docs`, `/redoc`) kapalıdır
- Rate limit: fotoğraf/story 10/dk, reel/carousel 5/dk
- Token süresi dolmak üzereyse (7 gün kala) webhook veya e-posta bildirimi gider
- Instagram'a doğrudan dosya yüklenemiyor; Cloudinary'e yükle → public URL al → Instagram'a ver
