# motor-hava

Gebze için motorcu odaklı günlük hava raporu: Open-Meteo → kural tabanlı sürüş skoru → 1080×1350 PNG kart → Telegram (her gün 08:30 Europe/Istanbul + `/now` komutu).
Proje notu (kararlar, durum, fikirler): https://claude.ai/code/artifact/a14ff966-b1b4-4019-bc1e-462b7e28f214

## Yapı
- `app/analysis.py` — fetch, saatlik parse, pencere puanlama (`_score_window`), ekipman (`_gear`), caption
- `app/render.py` — matplotlib kart (Inter font, koyu tema)
- `app/radar.py` — son 2 saatin radar GIF'i: RainViewer (en fazla z7, 512 px karo) + Esri koyu gri harita (anahtarsız); `/radar` komutu
- `app/main.py` — Telegram (`tg`, `_token`, `send`, `send_animation`), `job` + retry, `radar_job`, zamanlayıcı, `poll_commands` (/now, /radar, /help)
- `compose.yml` — Coolify (Docker Compose build pack, `/compose.yml`, domain yok) ve lokal compose

## Komutlar
```bash
cd app
python main.py --now --dry-run                      # gerçek API, Telegram'a göndermez, /out/rapor.png
OUT_DIR=/tmp/out python main.py --now --dry-run --sample veri.json   # API yerine Open-Meteo biçiminde JSON
python main.py --now                                # Telegram'a gönder (TELEGRAM_* env gerekli)
OUT_DIR=/tmp/out python main.py --radar --dry-run   # radar GIF'i üret, gönderme
```
`--sample` dosyasında `daily.time[7]` "bugün" sayılır (past_days=7 düzeni).

## Kurallar
- Deploy: `main`'e push → Coolify (vulut-server) otomatik deploy. Env değişikliği Redeploy ister.
- Bot token'ı ayrı bir bota ait; Mac'teki Claude Telegram eklentisinin token'ını KULLANMA (getUpdates 409 çakışması).
- Komutlar sadece `TELEGRAM_CHAT_ID`'den gelirse işlenir.
- Kullanıcı Türkçe konuşur; UI metinleri Türkçe.
