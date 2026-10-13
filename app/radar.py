"""Önümüzdeki 12 saatin yağış tahminini Gebze merkezli MP4 haritaya çevirir; görünüm iOS Hava
"Precipitation" haritasını örnek alır (Open-Meteo ICON-EU nokta ızgarası + Esri açık gri harita)."""
from __future__ import annotations

import io
import math
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import imageio_ffmpeg
import numpy as np
import requests
from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont

API = "https://api.open-meteo.com/v1/forecast"
MODEL = "icon_eu"  # 7 km; Türkiye'yi kapsayan en ince Open-Meteo modeli
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_{}/MapServer/tile/{{z}}/{{y}}/{{x}}"
_s = requests.Session()
_s.headers["User-Agent"] = "motor-hava/1.0"

Z = 9                # harita zoom'u (256 px karo) → ~232 m/px @ 40.8°K
W, H = 800, 1000     # ~185 × 230 km, telefon için dikey
STEP = 0.15          # ızgara aralığı (°); her nokta Open-Meteo'da 1 çağrı (dakikada 600 sınırı)
HOURS = 12
FPS, STEP_S, LAST_S = 10, 0.8, 2.5  # saat başına geçiş süresi; son kare daha uzun bekler

# mm/saat → renk/opaklık; aralar log ölçekte yumuşak geçiş (Hafif mavi → Orta mor → Kuvvetli
# eflatun → Aşırı sarı)
RAMP = [(0.05, (110, 160, 255, 0)), (0.2, (90, 140, 255, 90)), (1, (50, 90, 250, 160)),
        (3, (125, 75, 245, 195)), (7, (205, 70, 235, 210)), (15, (245, 90, 190, 220)),
        (30, (255, 225, 0, 230))]
_RX = np.log([m for m, _ in RAMP])
_RC = np.array([c for _, c in RAMP], dtype=np.float32).T  # (4, n)
LEGEND = ["Aşırı", "Kuvvetli", "Orta", "Hafif"]

INK, MUTED, TRACK, ACCENT = (20, 22, 26), (110, 116, 124), (215, 218, 224), (239, 68, 68)
CARD = (255, 255, 255, 235)
GUN = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
AY = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
      "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def _px(lat: float, lon: float, z: int, tile: int) -> tuple[float, float]:
    """Web Mercator global piksel koordinatı."""
    n = 2 ** z * tile
    s = math.sin(math.radians(lat))
    return (lon + 180) / 360 * n, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n


def _get(url: str) -> Image.Image:
    r = _s.get(url, timeout=20)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGBA")


def _mosaic(url: str, z: int, tile: int, x0: float, y0: float, w: int, h: int) -> Image.Image:
    """(x0, y0) sol üst köşeli w×h global piksel alanını karolardan birleştirir."""
    tx0, ty0 = int(x0 // tile), int(y0 // tile)
    tx1, ty1 = int((x0 + w) // tile), int((y0 + h) // tile)
    out = Image.new("RGBA", ((tx1 - tx0 + 1) * tile, (ty1 - ty0 + 1) * tile))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            out.paste(_get(url.format(z=z, x=tx, y=ty)), ((tx - tx0) * tile, (ty - ty0) * tile))
    ox, oy = int(x0) - tx0 * tile, int(y0) - ty0 * tile
    return out.crop((ox, oy, ox + w, oy + h))


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = font_manager.findfont(font_manager.FontProperties(
        family=["Inter", "DejaVu Sans"], weight="bold" if bold else "normal"))
    return ImageFont.truetype(path, size)


def _colorize(mm: np.ndarray) -> np.ndarray:
    x = np.log(np.clip(mm, RAMP[0][0], RAMP[-1][0]))
    rgba = np.stack([np.interp(x, _RX, ch) for ch in _RC], axis=-1)
    rgba[mm < RAMP[0][0]] = 0
    return rgba.astype(np.uint8)


def _forecast(lats: list[float], lons: list[float], tz: ZoneInfo) -> tuple[np.ndarray, list[datetime]]:
    """(saat, len(lats), len(lons)) mm/saat dizisi ve saatler. İlk saat = içinde bulunulan saat."""
    r = _s.get(API, timeout=60, params={
        "latitude": ",".join(f"{a:.4f}" for a in lats for _ in lons),
        "longitude": ",".join(f"{b:.4f}" for _ in lats for b in lons),
        "hourly": "precipitation", "forecast_hours": HOURS + 1, "models": MODEL,
        "timezone": tz.key})
    r.raise_for_status()
    data = r.json()
    grid = np.array([[v or 0 for v in p["hourly"]["precipitation"]] for p in data], dtype=np.float32)
    times = [datetime.fromisoformat(t).replace(tzinfo=tz) for t in data[0]["hourly"]["time"]]
    return grid.T.reshape(len(times), len(lats), len(lons)), times


def render_radar(lat: float, lon: float, place: str, tz: ZoneInfo, path: str) -> tuple[str, str]:
    """Videoyu path'e yazar; (path, caption) döner."""
    cx, cy = _px(lat, lon, Z, 256)
    x0, y0 = cx - W / 2, cy - H / 2
    # ızgara harita alanını bir aralık payla kapsasın; tek sayı → orta nokta tam konum
    deg = 360 / (2 ** Z * 256)
    ny = 2 * math.ceil((H / 2 * deg * math.cos(math.radians(lat)) + STEP) / STEP) + 1
    nx = 2 * math.ceil((W / 2 * deg + STEP) / STEP) + 1
    lats = [lat + STEP * (ny // 2 - i) for i in range(ny)]  # kuzeyden güneye
    lons = [lon + STEP * (j - nx // 2) for j in range(nx)]
    rain, times = _forecast(lats, lons, tz)

    base = _mosaic(ESRI.format("Base"), Z, 256, x0, y0, W, H)
    labels = _mosaic(ESRI.format("Reference"), Z, 256, x0, y0, W, H)  # yağışın üstüne

    # ızgara noktaları hücre merkezi: görüntü yarım hücre taşar; harita alanına denk gelen kısmı
    gx0, gy0 = _px(lats[0], lons[0], Z, 256)
    gx1, gy1 = _px(lats[-1], lons[-1], Z, 256)
    dx, dy = (gx1 - gx0) / (nx - 1), (gy1 - gy0) / (ny - 1)
    gw, gh = round(gx1 - gx0 + dx), round(gy1 - gy0 + dy)
    ox, oy = round(x0 - (gx0 - dx / 2)), round(y0 - (gy0 - dy / 2))

    def layer(mm: np.ndarray) -> Image.Image:
        up = np.asarray(Image.fromarray(mm).resize((gw, gh), Image.BICUBIC))
        return Image.fromarray(_colorize(up[oy:oy + H, ox:ox + W]))

    n = len(times)
    f_title, f_sub, f_time = _font(24, True), _font(17), _font(30, True)
    f_tick, f_leg, f_legh = _font(16), _font(15), _font(16, True)

    # sabit üst katman: açıklama kutusu, konum noktası, alt kart ve zaman çizelgesi zemini
    deco = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(deco)
    lx, ly = 18, 18
    d.rounded_rectangle((lx, ly, lx + 140, ly + 190), radius=18, fill=CARD)
    d.text((lx + 16, ly + 14), "Yağış", font=f_legh, fill=INK)
    gy_top, gy_bot = ly + 52, ly + 172
    mms = np.exp(np.linspace(math.log(30), math.log(0.3), gy_bot - gy_top)).astype(np.float32)
    for y, c in zip(range(gy_top, gy_bot), _colorize(mms)):
        d.line((lx + 18, y, lx + 23, y), fill=tuple(int(v) for v in c[:3]))
    for k, name in enumerate(LEGEND):
        d.text((lx + 36, gy_top + 6 + k * (gy_bot - gy_top - 12) / 3), name, font=f_leg,
               fill=MUTED, anchor="lm")
    d.ellipse((W / 2 - 9, H / 2 - 9, W / 2 + 9, H / 2 + 9), fill=ACCENT, outline=(255, 255, 255),
              width=3)
    kx0, ky0, kx1, ky1 = 18, H - 150, W - 18, H - 18
    d.rounded_rectangle((kx0, ky0, kx1, ky1), radius=26, fill=CARD)
    bx, bw, by = kx0 + 30, kx1 - kx0 - 60, ky0 + 82
    d.line((bx, by, bx + bw, by), fill=TRACK, width=8)
    for j in range(n):  # her saat bir çentik, iki saatte bir etiket
        x = bx + bw * j / (n - 1)
        d.line((x, by + 8, x, by + 14), fill=MUTED, width=2)
        if j % 2 == 0:
            d.text((x, by + 34), "Şimdi" if j == 0 else f"{times[j]:%H}", font=f_tick,
                   fill=INK if j == 0 else MUTED, anchor="ms")

    def frame(pos: float) -> bytes:
        """pos: 0..n-1 arası kesirli saat; saatler arası doğrusal geçiş."""
        i = min(int(pos), n - 2)
        f = pos - i
        im = base
        for l in (layer((1 - f) * rain[i] + f * rain[i + 1]), labels, deco):
            im = Image.alpha_composite(im, l)
        d = ImageDraw.Draw(im)
        t = times[round(pos)]
        d.text((kx0 + 30, ky0 + 22), "Tahmin", font=f_title, fill=INK)
        d.text((kx0 + 30, ky0 + 62), f"{t.day} {AY[t.month - 1]} {t.year} {GUN[t.weekday()]}",
               font=f_sub, fill=MUTED, anchor="lm")
        d.text((kx1 - 30, ky0 + 42), "Şimdi" if round(pos) == 0 else f"{t:%H:%M}",
               font=f_time, fill=INK, anchor="rm")
        d.line((bx, by, bx + bw * pos / (n - 1), by), fill=INK, width=8)
        return im.convert("RGB").tobytes()

    # MP4 (H.264): Telegram'da durdurulup sarılabiliyor; kareler akış halinde ffmpeg'e
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-movflags", "+faststart", path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    steps = round(STEP_S * FPS)
    for j in range((n - 1) * steps):
        p.stdin.write(frame(j / steps))
    last = frame(n - 1)
    for _ in range(round(LAST_S * FPS)):
        p.stdin.write(last)
    p.stdin.close()
    if p.wait():
        raise RuntimeError(f"ffmpeg hata kodu {p.returncode}")

    names = ["Şimdi"] + [f"{t:%H:%M}" for t in times[1:]]
    peak = rain.max(axis=(1, 2))
    wet = [names[j] for j in range(n) if rain[j, ny // 2, nx // 2] >= 0.1]  # orta nokta = konum
    here = (f"{place}'de yağışlı saat: {len(wet)}/{n}, ilki {wet[0]}" if wet
            else f"{place} üzerinde yağış beklenmiyor")
    text = (f"🌧 <b>{place} yağış tahmini</b> · Şimdi → {times[-1]:%H:%M}\n"
            f"{here}. Bölgedeki en yüksek: {peak.max():.1f} mm/sa ({names[int(peak.argmax())]}).\n"
            "<i>Model tahmini (ICON-EU 7 km), radar değil. Kırmızı nokta: "
            f"{place}.\nVeri: Open-Meteo / DWD · Harita: © Esri</i>")
    return path, text
