"""Son 2 saatin yağış radarını Gebze merkezli GIF'e çevirir (RainViewer + Esri koyu gri harita)."""
from __future__ import annotations

import io
import math
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont

RV_API = "https://api.rainviewer.com/public/weather-maps.json"
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_{}/MapServer/tile/{{z}}/{{y}}/{{x}}"
_s = requests.Session()  # ~85 karo; bağlantıyı yeniden kullan
_s.headers["User-Agent"] = "motor-hava/1.0"

Z = 10          # çıktı/harita zoom'u (256 px karo) → ~116 m/px @ 40.8°K
RZ = 7          # RainViewer ücretsiz API'de en yüksek zoom; 512 px karo = Z'nin 1/4 çözünürlüğü
SIZE = 900      # ~104 km kare
RADAR_ALPHA = 0.7

BG, TXT, MUTED, ACCENT = (14, 17, 22), (232, 234, 237), (154, 163, 173), (239, 68, 68)


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
    ox, oy = int(x0) - tx0 * tile, int(y0) - ty0 * tile  # kesir kısmı çağırana kalır
    return out.crop((ox, oy, ox + w, oy + h))


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = font_manager.findfont(font_manager.FontProperties(
        family=["Inter", "DejaVu Sans"], weight="bold" if bold else "normal"))
    return ImageFont.truetype(path, size)


def render_radar(lat: float, lon: float, place: str, tz: ZoneInfo, path: str) -> tuple[str, str]:
    """GIF'i path'e yazar; (path, caption) döner."""
    meta = _s.get(RV_API, timeout=20).json()
    frames = meta["radar"]["past"]
    if not frames:
        raise RuntimeError("RainViewer radar karesi döndürmedi")

    cx, cy = _px(lat, lon, Z, 256)
    x0, y0 = cx - SIZE / 2, cy - SIZE / 2
    base = _mosaic(ESRI.format("Base"), Z, 256, x0, y0, SIZE, SIZE)
    labels = _mosaic(ESRI.format("Reference"), Z, 256, x0, y0, SIZE, SIZE)  # radarın üstüne

    k = 2 ** Z * 256 / (2 ** RZ * 512)  # radar pikseli → çıktı pikseli ölçeği (4)
    rw = math.ceil(SIZE / k) + 2
    big, small, bold = _font(34, True), _font(20), _font(20, True)

    images, times = [], []
    for i, f in enumerate(frames):
        url = meta["host"] + f["path"] + "/512/{z}/{x}/{y}/2/1_1.png"
        r = _mosaic(url, RZ, 512, x0 / k, y0 / k, rw, rw)
        # Universal Blue'da <15 dBZ (çisenti/parazit) yarı saydam ten rengi; at, gerisini soldur
        r.putalpha(r.getchannel("A").point(lambda a: int(a * RADAR_ALPHA) if a >= 200 else 0))
        # büyüt, _mosaic'in attığı kesirli kaymayı ekleyip tam çıktı alanına kırp
        fx, fy = (x0 / k) % 1, (y0 / k) % 1
        r = r.resize((round(rw * k), round(rw * k)), Image.BILINEAR)
        r = r.crop((round(fx * k), round(fy * k), round(fx * k) + SIZE, round(fy * k) + SIZE))
        im = Image.alpha_composite(Image.alpha_composite(base, r), labels)

        d = ImageDraw.Draw(im)
        c = SIZE / 2
        d.ellipse((c - 7, c - 7, c + 7, c + 7), fill=ACCENT, outline=TXT, width=2)
        t = datetime.fromtimestamp(f["time"], tz)
        times.append(t)
        d.rounded_rectangle((20, 20, 250, 110), radius=14, fill=BG + (215,))
        d.text((38, 30), f"{t:%H:%M}", font=big, fill=TXT)
        d.text((38, 76), f"{place.upper()} · RADAR", font=small, fill=MUTED)
        # zaman çubuğu
        bx, by, bw = 20, SIZE - 34, SIZE - 40
        d.rounded_rectangle((bx, by, bx + bw, by + 10), radius=5, fill=(38, 44, 54))
        d.rounded_rectangle((bx, by, bx + max(10, bw * (i + 1) / len(frames)), by + 10),
                            radius=5, fill=TXT)
        if i == len(frames) - 1:
            d.text((SIZE - 20, 30), "SON KARE", font=bold, fill=ACCENT, anchor="ra")
        images.append(im.convert("RGB"))

    durations = [220] * (len(images) - 1) + [1600]
    images[0].save(path, save_all=True, append_images=images[1:], duration=durations, loop=0)

    text = (f"🌧 <b>{place} radar</b> · {times[0]:%H:%M}–{times[-1]:%H:%M}\n"
            f"Kırmızı nokta: {place}. Yağış bantlarının yönüne bak.\n"
            '<i>Radar: <a href="https://www.rainviewer.com">RainViewer</a> · '
            "Harita: © Esri</i>")
    return path, text
