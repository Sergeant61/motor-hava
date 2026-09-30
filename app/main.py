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
import sys
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
def tg(method: str, **kw) -> dict:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}", timeout=30, **kw)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} hatası: {data}")
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
def job(dry: bool = False, sample: str | None = None) -> str:
    cfg = Config()
    today = datetime.now(TZ).date()
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
