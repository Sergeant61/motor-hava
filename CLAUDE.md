# motor-hava

Gebze için motorcu odaklı günlük hava raporu: Open-Meteo → kural tabanlı sürüş skoru → 1080×1350 PNG kart → Telegram (her gün 08:30 Europe/Istanbul + `/now` komutu).
Proje notu (kararlar, durum, fikirler): https://claude.ai/code/artifact/a14ff966-b1b4-4019-bc1e-462b7e28f214

## Yapı
- `app/analysis.py` — fetch, saatlik parse, pencere puanlama (`_score_window`), ekipman (`_gear`), caption
- `app/render.py` — matplotlib kart (Inter font, koyu tema)
- `app/radar.py` — önümüzdeki 12 saatin yağış tahmini videosu (MP4, `imageio-ffmpeg`), görünüm iOS Hava "Precipitation" haritası örnek alınarak: Open-Meteo ICON-EU, 0.15° nokta ızgarası (~300 nokta; her nokta 1 çağrı, dakikada 600 sınırı) + Esri açık gri harita (anahtarsız); `/radar` komutu. Gerçek radar (RainViewer) ücretsiz API'de sadece geçmiş 2 saati veriyor, ileriye dönük değil
- `app/main.py` — Telegram (`tg`, `_token`, `send`, `send_video`), `job` + retry, `radar_job`, zamanlayıcı, `poll_commands` (/now, /radar, /help)
- `compose.yml` — Coolify (Docker Compose build pack, `/compose.yml`, domain yok) ve lokal compose

## Komutlar
```bash
cd app
python main.py --now --dry-run                      # gerçek API, Telegram'a göndermez, /out/rapor.png
OUT_DIR=/tmp/out python main.py --now --dry-run --sample veri.json   # API yerine Open-Meteo biçiminde JSON
python main.py --now                                # Telegram'a gönder (TELEGRAM_* env gerekli)
OUT_DIR=/tmp/out python main.py --radar --dry-run   # yağış tahmini videosu üret, gönderme
```
`--sample` dosyasında `daily.time[7]` "bugün" sayılır (past_days=7 düzeni).

## Kurallar
- Deploy: `main`'e push → Coolify (vulut-server) otomatik deploy. Env değişikliği Redeploy ister.
- Bot token'ı ayrı bir bota ait; Mac'teki Claude Telegram eklentisinin token'ını KULLANMA (getUpdates 409 çakışması).
- Komutlar sadece `TELEGRAM_CHAT_ID`'den gelirse işlenir.
- Kullanıcı Türkçe konuşur; UI metinleri Türkçe.
