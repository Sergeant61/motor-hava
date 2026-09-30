"""Motorcu hava raporu — her gün SEND_TIME'da (Europe/Istanbul) Telegram'a gönderir.

Kullanım:
  python main.py                 # zamanlayıcı modu (container'da varsayılan)
  python main.py --now           # hemen bir kez gönder ve çık
  python main.py --now --dry-run # göndermeden /out/rapor.png üret
  python main.py --now --dry-run --sample veri.json   # API yerine dosyadan
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from analysis import Config, analyze, caption, fetch
from render import render

log = logging.getLogger("motor-hava")
TZ = ZoneInfo(os.getenv("TZ", "Europe/Istanbul"))
OUT = os.getenv("OUT_DIR", "/out")


# ---------------------------------------------------------------- telegram
def _token() -> str:
    """Sık yapılan yapıştırma hatalarını temizler: tırnak, boşluk, 'VAR=' öneki, 'bot' öneki."""
    t = os.environ["TELEGRAM_BOT_TOKEN"].strip().strip("'\"").strip()
    if "=" in t:
        t = t.split("=", 1)[1].strip().strip("'\"")
    if t.lower().startswith("bot") and ":" in t:
        t = t[3:]
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{30,}", t):
        raise RuntimeError(
            f"TELEGRAM_BOT_TOKEN biçimi hatalı (uzunluk {len(t)}, başı {t[:4]!r}…). "
            "Beklenen: 123456789:AA… şeklinde tek parça değer.")
    return t


def tg(method: str, **kw) -> dict:
    r = requests.post(f"https://api.telegram.org/bot{_token()}/{method}", timeout=30, **kw)
    data = r.json()
    if not data.get("ok"):
        hint = ""
        if data.get("error_code") == 404:
            hint = " → Token geçersiz/eksik kopyalanmış (Telegram yanlış token'a 404 döner)."
        elif data.get("error_code") == 401:
            hint = " → Token iptal edilmiş; BotFather'dan güncelini al."
        elif "chat not found" in str(data.get("description", "")):
            hint = " → TELEGRAM_CHAT_ID yanlış ya da bota hiç /start yazılmamış."
        raise RuntimeError(f"Telegram {method} hatası: {data}{hint}")
    return data


def send(png: str, text: str) -> None:
    chat = os.environ["TELEGRAM_CHAT_ID"]
    short = text if len(text) <= 1024 else text[:1000].rsplit("\n", 1)[0] + "\n…"
    with open(png, "rb") as f:
        tg("sendPhoto", data={"chat_id": chat, "caption": short, "parse_mode": "HTML"},
           files={"photo": ("rapor.png", f, "image/png")})
    if short != text:
        tg("sendMessage", data={"chat_id": chat, "text": text, "parse_mode": "HTML"})


# ---------------------------------------------------------------- job
_lock = threading.Lock()  # zamanlanmış gönderim ile /now aynı anda çalışmasın


def job(dry: bool = False, sample: str | None = None) -> str:
    with _lock:
        return _job(dry, sample)


def _job(dry: bool, sample: str | None) -> str:
    cfg = Config()
    now = datetime.now(TZ)
    today = now.date()
    if now.hour >= cfg.evening[1]:  # akşam dönüşü geçtiyse yarının raporu daha anlamlı
        today += timedelta(days=1)
    if sample:
        raw = json.load(open(sample))
        today = datetime.fromisoformat(raw["daily"]["time"][7]).date()  # past_days=7 → 8. gün bugün
    else:
        raw = fetch(cfg)
    rep = analyze(raw, cfg, today)
    os.makedirs(OUT, exist_ok=True)
    png = render(rep, os.path.join(OUT, "rapor.png"))
    text = caption(rep)
    log.info("Skor %s (%s) — %d uyarı", rep.score, rep.verdict, len(rep.warnings))
    if dry:
        print(text)
    else:
        send(png, text)
        log.info("Telegram'a gönderildi")
    return png


def job_with_retry(**kw) -> None:
    delays = [0, 60, 180, 600]
    for i, d in enumerate(delays):
        time.sleep(d)
        try:
            job(**kw)
            return
        except Exception as e:  # ağ, API, Telegram
            log.exception("Deneme %d başarısız: %s", i + 1, e)
    try:
        tg("sendMessage", data={"chat_id": os.environ["TELEGRAM_CHAT_ID"],
                                "text": "⚠️ Bugünkü hava raporu üretilemedi, logları kontrol et."})
    except Exception:
        log.exception("Hata bildirimi de gönderilemedi")


# ---------------------------------------------------------------- bot komutları
HELP = ("<b>Komutlar</b>\n"
        "/now – raporu şimdi gönder (20:00 sonrası yarının raporu)\n"
        "/help – bu mesaj")


def reply(text: str) -> None:
    tg("sendMessage", data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text,
                            "parse_mode": "HTML"})


def handle(text: str) -> None:
    cmd = text.strip().split()[0].split("@")[0].lower()
    if cmd in ("/now", "/rapor", "/hava"):
        reply("⏳ Rapor hazırlanıyor…")
        try:
            job()
        except Exception as e:
            log.exception("/now başarısız")
            reply(f"⚠️ Rapor üretilemedi: {e}"[:400])
    elif cmd in ("/start", "/help"):
        reply(HELP)


def poll_commands() -> None:
    """getUpdates long-polling. Sadece TELEGRAM_CHAT_ID'den gelen mesajlar işlenir."""
    owner = str(os.environ["TELEGRAM_CHAT_ID"])
    try:
        tg("deleteWebhook")
        tg("setMyCommands", json={"commands": [
            {"command": "now", "description": "Raporu şimdi gönder"},
            {"command": "help", "description": "Yardım"}]})
    except Exception:
        log.exception("Bot komut kurulumu başarısız")
    offset = None
    log.info("Bot komutları dinleniyor (/now, /help)")
    while True:
        try:
            params = {"timeout": 50, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset
            r = requests.post(f"https://api.telegram.org/bot{_token()}/getUpdates",
                              json=params, timeout=60)
            data = r.json()
            if data.get("error_code") == 409:
                log.warning("409: Bu bot token'ını başka bir süreç de dinliyor "
                            "(ör. Claude Telegram eklentisi). Ayrı bir bot kullan. 5 dk bekleniyor.")
                time.sleep(300)
                continue
            for u in data.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != owner:
                    continue  # yabancıları yok say
                if (msg.get("text") or "").startswith("/"):
                    handle(msg["text"])
        except Exception:
            log.exception("getUpdates hatası")
            time.sleep(10)


def next_run(now: datetime, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return t if t > now else t + timedelta(days=1)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--now", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--sample")
    a = p.parse_args()

    if a.now:
        if a.dry_run:
            job(dry=True, sample=a.sample)
        else:
            job_with_retry(sample=a.sample)
        return

    if os.getenv("ENABLE_COMMANDS", "true").lower() == "true":
        threading.Thread(target=poll_commands, daemon=True).start()

    send_time = os.getenv("SEND_TIME", "08:30")
    log.info("Zamanlayıcı başladı — her gün %s (%s)", send_time, TZ.key)
    while True:
        target = next_run(datetime.now(TZ), send_time)
        log.info("Sonraki gönderim: %s", target.isoformat())
        # uzun uykuda saat kaymasına karşı parça parça bekle
        while (left := (target - datetime.now(TZ)).total_seconds()) > 0:
            time.sleep(min(left, 300))
        job_with_retry()


if __name__ == "__main__":
    sys.exit(main())
