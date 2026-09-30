"""Open-Meteo verisini motorcu gözüyle analiz eder: sürüş skoru, uyarılar, ekipman."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, date

import requests

API = "https://api.open-meteo.com/v1/forecast"

HOURLY = [
    "temperature_2m", "apparent_temperature", "relative_humidity_2m",
    "precipitation_probability", "precipitation", "weather_code",
    "wind_speed_10m", "wind_gusts_10m", "visibility",
]
DAILY = ["sunrise", "sunset", "precipitation_sum", "temperature_2m_max", "temperature_2m_min"]

WMO = {
    0: "Açık", 1: "Çoğunlukla açık", 2: "Parçalı bulutlu", 3: "Kapalı",
    45: "Sis", 48: "Kırağılı sis",
    51: "Hafif çisenti", 53: "Çisenti", 55: "Yoğun çisenti",
    56: "Dondurucu çisenti", 57: "Dondurucu çisenti",
    61: "Hafif yağmur", 63: "Yağmur", 65: "Şiddetli yağmur",
    66: "Dondurucu yağmur", 67: "Dondurucu yağmur",
    71: "Hafif kar", 73: "Kar", 75: "Yoğun kar", 77: "Kar taneleri",
    80: "Hafif sağanak", 81: "Sağanak", 82: "Şiddetli sağanak",
    85: "Kar sağanağı", 86: "Yoğun kar sağanağı",
    95: "Gök gürültülü sağanak", 96: "Dolu + fırtına", 99: "Dolu + fırtına",
}


# ---------------------------------------------------------------- config
@dataclass
class Config:
    lat: float = float(os.getenv("LAT", "40.8028"))
    lon: float = float(os.getenv("LON", "29.4307"))
    location: str = os.getenv("LOCATION_NAME", "Gebze")
    morning: tuple[int, int] = tuple(int(x) for x in os.getenv("MORNING_WINDOW", "8-10").split("-"))
    evening: tuple[int, int] = tuple(int(x) for x in os.getenv("EVENING_WINDOW", "17-20").split("-"))
    ride_speed: float = float(os.getenv("RIDE_SPEED_KMH", "60"))
    timezone: str = os.getenv("TZ", "Europe/Istanbul")


def fetch(cfg: Config) -> dict:
    params = {
        "latitude": cfg.lat, "longitude": cfg.lon,
        "hourly": ",".join(HOURLY), "daily": ",".join(DAILY),
        "timezone": cfg.timezone, "past_days": 7, "forecast_days": 2,
        "wind_speed_unit": "kmh",
    }
    r = requests.get(API, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------- physics
def ride_chill(t: float, v: float) -> float:
    """Sürüş hızında hissedilen sıcaklık (Environment Canada wind-chill formülü).
    Formül T<=10°C için kalibre; üstünde de yönü doğru, değeri T ile sınırlıyoruz."""
    v = max(v, 5.0)
    wc = 13.12 + 0.6215 * t - 11.37 * v ** 0.16 + 0.3965 * t * v ** 0.16
    return min(t, wc)


# ---------------------------------------------------------------- model
@dataclass
class Hour:
    time: datetime
    temp: float
    feels: float
    rh: float
    pp: float          # yağış olasılığı %
    precip: float      # mm
    code: int
    wind: float
    gust: float
    vis: float         # metre
    chill: float       # sürüşte hissedilen


@dataclass
class Window:
    name: str
    start: int
    end: int
    hours: list[Hour]
    score: int = 100
    reasons: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.start:02d}–{self.end:02d}"

    def agg(self):
        h = self.hours
        return dict(
            tmin=min(x.temp for x in h), tmax=max(x.temp for x in h),
            chill=min(x.chill for x in h), pp=max(x.pp for x in h),
            precip=sum(x.precip for x in h), gust=max(x.gust for x in h),
            vis=min(x.vis for x in h), code=max(h, key=lambda x: _severity(x.code)).code,
        )


@dataclass
class Report:
    day: date
    location: str
    hours: list[Hour]          # bugünün 00–23 saatleri
    windows: list[Window]
    score: int
    level: str                 # green | amber | red
    verdict: str
    warnings: list[str]
    gear: list[str]
    road: str
    sunrise: datetime
    sunset: datetime
    tmin: float
    tmax: float
    dry_days: int


def _severity(code: int) -> int:
    if code >= 95: return 9
    if code in (56, 57, 66, 67) or 71 <= code <= 86: return 8
    if code in (65, 82): return 7
    if code in (63, 81): return 6
    if code in (61, 80, 55): return 5
    if code in (51, 53): return 4
    if code in (45, 48): return 3
    return code  # 0-3


def _parse(raw: dict, ride_speed: float) -> list[Hour]:
    h = raw["hourly"]
    out = []
    for i, ts in enumerate(h["time"]):
        t = h["temperature_2m"][i]
        if t is None:
            continue
        out.append(Hour(
            time=datetime.fromisoformat(ts), temp=t,
            feels=h["apparent_temperature"][i] or t,
            rh=h["relative_humidity_2m"][i] or 0,
            pp=h["precipitation_probability"][i] or 0,
            precip=h["precipitation"][i] or 0,
            code=h["weather_code"][i] or 0,
            wind=h["wind_speed_10m"][i] or 0,
            gust=h["wind_gusts_10m"][i] or 0,
            vis=h["visibility"][i] if h["visibility"][i] is not None else 24000,
            chill=ride_chill(t, ride_speed),
        ))
    return out


def _dry_days(raw: dict, today: date) -> int:
    d = raw["daily"]
    days = [(date.fromisoformat(t), p or 0) for t, p in zip(d["time"], d["precipitation_sum"])]
    n = 0
    for dt, p in sorted((x for x in days if x[0] < today), reverse=True):
        if p >= 1.0:
            break
        n += 1
    return n


# ---------------------------------------------------------------- scoring
def _score_window(w: Window, prior: list[Hour], dry_days: int) -> None:
    a = w.agg()
    pen, rs = 0, []

    def hit(p, msg):
        nonlocal pen
        pen += p
        rs.append((p, msg))

    if _severity(a["code"]) == 9:
        hit(40, "Gök gürültülü sağanak / dolu riski")
    if a["code"] in (56, 57, 66, 67) or 71 <= a["code"] <= 86:
        hit(40, f"{WMO.get(a['code'], 'Kış yağışı')}")

    if a["pp"] >= 70:   hit(30, f"Yağış çok olası (%{a['pp']:.0f})")
    elif a["pp"] >= 50: hit(20, f"Yağış olası (%{a['pp']:.0f})")
    elif a["pp"] >= 30: hit(10, f"Yağış ihtimali (%{a['pp']:.0f})")
    elif a["pp"] >= 15: pen += 4

    if a["precip"] >= 3:     hit(20, f"Kuvvetli yağış ({a['precip']:.1f} mm)")
    elif a["precip"] >= 1:   hit(12, f"Yağış ({a['precip']:.1f} mm)")
    elif a["precip"] >= 0.2: pen += 6

    if a["gust"] >= 60:   hit(40, f"Tehlikeli rüzgar hamlesi ({a['gust']:.0f} km/h)")
    elif a["gust"] >= 50: hit(30, f"Sert rüzgar hamlesi ({a['gust']:.0f} km/h)")
    elif a["gust"] >= 40: hit(18, f"Kuvvetli hamle ({a['gust']:.0f} km/h) – yan rüzgara dikkat")
    elif a["gust"] >= 30: hit(8, f"Rüzgarlı ({a['gust']:.0f} km/h hamle)")

    if a["chill"] < 0:    hit(30, f"Sürüşte ~{a['chill']:.0f}°C hissedilir – donma soğuğu")
    elif a["chill"] < 5:  hit(18, f"Sürüşte ~{a['chill']:.0f}°C hissedilir – çok soğuk")
    elif a["chill"] < 10: hit(8, f"Sürüşte ~{a['chill']:.0f}°C hissedilir")
    if a["tmax"] >= 33:   hit(10, f"Sıcak ({a['tmax']:.0f}°C) – sıvı kaybı")

    if a["vis"] < 1000:   hit(20, f"Sis – görüş {a['vis']/1000:.1f} km")
    elif a["vis"] < 3000: hit(8, f"Görüş düşük ({a['vis']/1000:.1f} km)")

    icing = any(x.temp <= 4 and (x.rh >= 85 or x.precip > 0) for x in w.hours)
    if icing:
        hit(40, "Buzlanma riski – köprü ve gölgelik yerler")

    wet_before = sum(x.precip for x in prior) >= 0.2
    raining = a["precip"] >= 0.2
    if wet_before and not raining:
        hit(8, "Yol ıslak olabilir (önceki saatlerde yağış)")
    if (wet_before or raining) and dry_days >= 5:
        hit(10, f"{dry_days} gün kuraklıktan sonra ilk yağmur – yol çok kaygan")

    w.score = max(0, 100 - pen)
    w.reasons = rs  # (ceza, mesaj)


def _level(score: int) -> tuple[str, str]:
    if score >= 75: return "green", "Sürüş için uygun"
    if score >= 50: return "amber", "Dikkatli sür"
    return "red", "Mümkünse motoru bırak"


def _gear(windows: list[Window], sunset: datetime, evening: Window) -> list[str]:
    ag = [w.agg() for w in windows]
    chill = min(a["chill"] for a in ag)
    pp = max(a["pp"] for a in ag)
    precip = sum(a["precip"] for a in ag)
    vis = min(a["vis"] for a in ag)
    rh = max(x.rh for w in windows for x in w.hours)
    g = []
    if chill < 5:
        g += ["Kışlık mont + termal içlik", "Kışlık eldiven + boyunluk"]
    elif chill < 12:
        g += ["Astarlı mont", "Orta sezon eldiven + boyunluk"]
    elif chill < 20:
        g += ["Astarsız mont", "İnce eldiven"]
    else:
        g += ["Fileli yazlık mont", "Yazlık eldiven"]
    if pp >= 30 or precip >= 0.2:
        g.append("Yağmurluk + su geçirmez kılıf")
    if vis < 3000 or (chill < 12 and rh >= 85):
        g.append("Pinlock / buğu önleyici")
    if sunset.hour * 60 + sunset.minute < evening.end * 60:
        g.append("Yansıtıcı yelek (dönüş karanlık)")
    return g


# ---------------------------------------------------------------- main
def analyze(raw: dict, cfg: Config, today: date) -> Report:
    allh = _parse(raw, cfg.ride_speed)
    hours = [h for h in allh if h.time.date() == today]
    d = raw["daily"]
    idx = d["time"].index(today.isoformat())
    sunrise = datetime.fromisoformat(d["sunrise"][idx])
    sunset = datetime.fromisoformat(d["sunset"][idx])
    dry = _dry_days(raw, today)

    def mk(name, rng):
        s, e = rng
        win = [h for h in hours if s <= h.time.hour < e]
        start = datetime.combine(today, datetime.min.time()).replace(hour=s)
        prior = [h for h in allh if 0 < (start - h.time).total_seconds() / 3600 <= 4]
        w = Window(name, s, e, win)
        _score_window(w, prior, dry)
        return w

    morning = mk("Sabah", cfg.morning)
    evening = mk("Akşam", cfg.evening)
    windows = [morning, evening]
    score = min(w.score for w in windows)
    level, verdict = _level(score)

    # uyarıları ağırlığa göre sırala (en tehlikelisi üstte)
    ranked = sorted(((p, f"{w.name}: {m}") for w in windows for p, m in w.reasons),
                    key=lambda x: -x[0])
    warnings: list[str] = []
    for _, item in ranked:
        if item not in warnings:
            warnings.append(item)
    day_gust = max((h.gust for h in hours if 6 <= h.time.hour <= 23), default=0)
    if day_gust >= 50 and all(w.agg()["gust"] < 50 for w in windows):
        warnings.append(f"Gün içinde {day_gust:.0f} km/h hamle bekleniyor")

    wet_now = sum(h.precip for h in allh if 0 < (datetime.combine(today, datetime.min.time()).replace(hour=cfg.morning[0]) - h.time).total_seconds() / 3600 <= 6) >= 0.2
    if any(w.agg()["precip"] >= 0.2 for w in windows):
        road = "Islak"
    elif wet_now:
        road = "Islak olabilir"
    else:
        road = "Kuru"

    return Report(
        day=today, location=cfg.location, hours=hours, windows=windows,
        score=score, level=level, verdict=verdict, warnings=warnings,
        gear=_gear(windows, sunset, evening), road=road,
        sunrise=sunrise, sunset=sunset,
        tmin=d["temperature_2m_min"][idx], tmax=d["temperature_2m_max"][idx],
        dry_days=dry,
    )


# ---------------------------------------------------------------- caption
DOT = {"green": "🟢", "amber": "🟡", "red": "🔴"}


def caption(rep: Report) -> str:
    lines = [f"<b>🏍 {rep.location} · Sürüş skoru {rep.score}/100</b>",
             f"{DOT[rep.level]} <b>{rep.verdict}</b>", ""]
    for w in rep.windows:
        a = w.agg()
        lines.append(
            f"<b>{w.name} {w.label}</b>: {a['tmin']:.0f}°C (sürüşte ~{a['chill']:.0f}°C), "
            f"yağış %{a['pp']:.0f}, hamle {a['gust']:.0f} km/h"
        )
    lines.append(f"Yol: {rep.road}")
    if rep.warnings:
        lines.append("")
        lines += [f"⚠️ {w}" for w in rep.warnings[:5]]
    lines += ["", "👕 " + " · ".join(rep.gear)]
    return "\n".join(lines)
