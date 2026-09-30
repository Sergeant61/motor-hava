# motor-hava 🏍

Her sabah 08:30'da (Europe/Istanbul) Gebze için motorcu odaklı hava raporunu görsel kart + özet olarak Telegram'a gönderir.

- **Veri:** Open-Meteo (API anahtarı gerekmez). Saatlik yağış, rüzgar hamlesi, görüş ve son 7 günün yağışı çekilir.
- **Analiz:** Sabah (08–10) ve akşam (17–20) pencereleri ayrı ayrı puanlanır. Günün skoru, iki pencereden kötü olanın skorudur.
- **Kurallar:** Yağış olasılığı/miktarı, hamle (30/40/50/60 km/h eşikleri), 60 km/h hızda hissedilen sıcaklık, sis, buzlanma, ıslak yol ve "kuraklık sonrası ilk yağmur".
- **Çıktı:** 1080×1350 PNG kart + HTML caption. Hata olursa 4 kez yeniden denenir; hepsi başarısız olursa Telegram'a hata mesajı gelir.

## Kurulum (Contabo VPS)

### 1. Token ve chat ID
- **Token:** Mac'teki Claude Telegram eklentisinin kullandığı bot token'ı. Genelde `~/.claude/channels/telegram/.env` dosyasında `TELEGRAM_BOT_TOKEN` olarak durur.
- **Chat ID:** Kendi Telegram kullanıcı ID'n. Eklentinin `access.json` dosyasındaki izinli listede yazıyor; bulamazsan Telegram'da @userinfobot'a yazarak öğrenebilirsin.
  > Aynı botta `getUpdates` çağırma: eklenti zaten polling yapıyor, ikisi çakışır. Bu servis yalnızca `sendPhoto`/`sendMessage` kullandığı için eklentiyle çakışmaz.

### 2A. Coolify ile (önerilen)
1. **GitHub'a private repo olarak push et:**
   ```bash
   cd motor-hava
   git init && git add . && git commit -m "motor-hava ilk sürüm"
   gh repo create Sergeant61/motor-hava --private --source . --push
   ```
   Coolify'ın GitHub App'i "Only select repositories" modundaysa, GitHub → Settings → Applications → Coolify App → **Repository access** kısmına `motor-hava`'yı ekle. Yoksa repo listede görünmez.
2. **Coolify → Projects → + New → Private Repository (with GitHub App)** → `motor-hava`, branch `main`.
   - Server: Contabo'ya karşılık gelen sunucu
   - **Build Pack: Docker Compose**
   - Docker Compose Location: `/compose.yml`
3. **Domain alanını boş bırak.** Bu bir worker; port açmıyor, domain gerekmiyor.
4. **Environment Variables** sekmesi: Coolify, `compose.yml` içindeki `${...}` değişkenlerini otomatik listeler.
   - `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` zorunlu, bunları gir.
   - Diğerlerinin varsayılanı dolu gelir.
5. **Deploy.** Logs sekmesinde `Sonraki gönderim: 2026-..T08:30:00+03:00` satırını görmelisin.
6. **Hemen test:** Uygulamanın **Terminal** sekmesinden container'a gir ve şunu çalıştır:
   ```bash
   python main.py --now            # Telegram'a hemen gönderir
   python main.py --now --dry-run  # göndermeden sadece özet yazar
   ```
7. İstersen **Webhooks → Auto Deploy** açık kalsın; `git push` sonrası otomatik yeniden deploy eder.

### 2B. Coolify'sız, düz Docker Compose
```bash
scp -r motor-hava contabo:~/ && ssh contabo
cd ~/motor-hava && cp .env.example .env && nano .env
docker compose up -d --build
docker compose exec motor-hava python main.py --now   # test
docker compose logs -f
```

## Ayarlar (.env)
| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `SEND_TIME` | `08:30` | Gönderim saati |
| `MORNING_WINDOW` / `EVENING_WINDOW` | `8-10` / `17-20` | Puanlanan sürüş pencereleri |
| `RIDE_SPEED_KMH` | `60` | "Sürüşte hissedilen" hesabındaki hız |
| `LAT` / `LON` / `LOCATION_NAME` | Gebze merkez | Konum |

## Skor mantığı (özet)
Her pencere 100 puandan başlar ve cezalar düşülür:

| Durum | Ceza |
|---|---|
| Fırtına, dolu veya kış yağışı | −40 |
| Buzlanma (≤4°C ve nem/yağış) | −40 |
| Hamle ≥60 / 50 / 40 / 30 km/h | −40 / −30 / −18 / −8 |
| Yağış olasılığı ≥%70 / 50 / 30 | −30 / −20 / −10 |
| Yağış miktarı ≥3 / 1 mm | −20 / −12 |
| Sürüşte hissedilen <0 / 5 / 10°C | −30 / −18 / −8 |
| Görüş <1 / 3 km | −20 / −8 |
| Islak yol | −8 |
| Kuraklık sonrası ilk yağmur | −10 |

Sonuç: **75 ve üstü** 🟢 Sürüş için uygun · **50–74** 🟡 Dikkatli sür · **50 altı** 🔴 Mümkünse motoru bırak.

Eşikler `app/analysis.py` içindeki `_score_window` fonksiyonundan değiştirilebilir.
