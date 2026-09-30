"""Raporu 1080x1350 PNG karta çevirir (Telegram portre)."""
from __future__ import annotations

import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

from analysis import Report, WMO

BG, CARD, LINE = "#0e1116", "#171b22", "#262c36"
TXT, MUTED, FAINT = "#e8eaed", "#9aa3ad", "#5c6570"
C = {"green": "#22c55e", "amber": "#f5a524", "red": "#ef4444"}
RAIN, TEMP, SUN = "#3b82f6", "#fb923c", "#facc15"

GUN = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
AY = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
      "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]

plt.rcParams["font.family"] = ["Inter", "DejaVu Sans"]


def _lvl(score: int) -> str:
    return "green" if score >= 75 else "amber" if score >= 50 else "red"


def _gust_color(g: float) -> str:
    return C["red"] if g >= 50 else C["amber"] if g >= 30 else MUTED


def _box(fig, x, y, w, h, color=CARD, r=0.018, ec=None):
    fig.add_artist(FancyBboxPatch(
        (x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
        transform=fig.transFigure, fc=color, ec=ec or color, lw=1.2,
        mutation_aspect=1080 / 1350, zorder=-10))


def render(rep: Report, path: str) -> str:
    fig = plt.figure(figsize=(7.2, 9.0), dpi=150, facecolor=BG)
    T = fig.text
    L, R = 0.055, 0.945

    # --- başlık
    T(L, 0.955, rep.location.upper(), color=MUTED, fontsize=10, weight="bold", va="center")
    T(L, 0.928, f"{rep.day.day} {AY[rep.day.month-1]} {GUN[rep.day.weekday()]}",
      color=TXT, fontsize=17, weight="bold", va="center")
    T(R, 0.955, f"{rep.tmin:.0f}° / {rep.tmax:.0f}°", color=TXT, fontsize=13,
      weight="bold", ha="right", va="center")
    T(R, 0.928, f"↑ {rep.sunrise:%H:%M}   ↓ {rep.sunset:%H:%M}", color=MUTED,
      fontsize=9.5, ha="right", va="center")

    # --- skor bloğu
    col = C[rep.level]
    _box(fig, L, 0.765, R - L, 0.135, ec=LINE)
    _box(fig, L, 0.765, 0.012, 0.135, color=col, r=0.006)
    T(L + 0.05, 0.832, f"{rep.score}", color=col, fontsize=48, weight="bold", va="center")
    T(L + 0.05, 0.783, "SÜRÜŞ SKORU", color=MUTED, fontsize=8, weight="bold", va="center")
    T(0.36, 0.855, rep.verdict, color=TXT, fontsize=17, weight="bold", va="center")
    sub = f"Yol: {rep.road}"
    if rep.dry_days >= 5 and rep.road != "Kuru":
        sub += f"  ·  {rep.dry_days} gün sonra ilk yağmur"
    T(0.36, 0.818, sub, color=MUTED, fontsize=10, va="center")
    # skor çubuğu
    bx, bw, by = 0.36, R - 0.36 - 0.035, 0.787
    _box(fig, bx, by, bw, 0.010, color=LINE, r=0.005)
    _box(fig, bx, by, max(0.012, bw * rep.score / 100), 0.010, color=col, r=0.005)

    # --- sabah / akşam kartları
    cw = (R - L - 0.03) / 2
    for i, w in enumerate(rep.windows):
        a = w.agg()
        x = L + i * (cw + 0.03)
        y0, hgt = 0.535, 0.21
        wl = _lvl(w.score)
        _box(fig, x, y0, cw, hgt, ec=LINE)
        T(x + 0.03, y0 + hgt - 0.028, f"{w.name.upper()}  {w.label}", color=MUTED,
          fontsize=9, weight="bold", va="center")
        T(x + cw - 0.03, y0 + hgt - 0.028, f"{w.score}", color=C[wl], fontsize=12,
          weight="bold", ha="right", va="center")
        tval = f"{a['tmin']:.0f}°" if round(a["tmin"]) == round(a["tmax"]) else f"{a['tmin']:.0f}–{a['tmax']:.0f}°"
        T(x + 0.03, y0 + hgt - 0.078, tval, color=TXT, fontsize=26, weight="bold", va="center")
        T(x + 0.03, y0 + hgt - 0.113, WMO.get(a["code"], ""), color=MUTED, fontsize=9.5, va="center")
        rows = [
            ("Sürüşte", f"~{a['chill']:.0f}°C", TXT),
            ("Yağış", f"%{a['pp']:.0f} · {a['precip']:.1f} mm", RAIN if a["pp"] >= 30 else TXT),
            ("Hamle", f"{a['gust']:.0f} km/h", _gust_color(a["gust"]) if a["gust"] >= 30 else TXT),
        ]
        for j, (k, v, vc) in enumerate(rows):
            yy = y0 + 0.068 - j * 0.024
            T(x + 0.03, yy, k, color=MUTED, fontsize=9, va="center")
            T(x + cw - 0.03, yy, v, color=vc, fontsize=9.5, weight="bold", ha="right", va="center")

    # --- 24 saat zaman şeridi
    hrs = [h for h in rep.hours if 6 <= h.time.hour <= 23]
    xs = [h.time.hour for h in hrs]
    _box(fig, L, 0.265, R - L, 0.25, ec=LINE)
    T(L + 0.03, 0.492, "GÜN BOYU", color=MUTED, fontsize=9, weight="bold", va="center")
    T(R - 0.03, 0.492, "━ sıcaklık   ▮ yağış %   hamle km/h", color=FAINT,
      fontsize=7.5, ha="right", va="center")
    ax = fig.add_axes([L + 0.045, 0.325, R - L - 0.09, 0.145], facecolor=CARD)
    ax.bar(xs, [h.pp for h in hrs], width=0.72, color=RAIN, alpha=0.55, zorder=2)
    for h in hrs:
        if h.pp >= 20:
            ax.text(h.time.hour, h.pp + 3, f"{h.pp:.0f}", color=RAIN, fontsize=6.5,
                    ha="center", va="bottom", zorder=4)
    ax.set_ylim(0, 175)
    ax.set_xlim(5.4, 23.6)
    for w in rep.windows:
        ax.axvspan(w.start - 0.5, w.end - 0.5, color="#ffffff", alpha=0.045, zorder=1, lw=0)
    sh = rep.sunset.hour + rep.sunset.minute / 60
    ax.axvline(sh, color=SUN, lw=1, ls=(0, (2, 3)), alpha=0.7, zorder=1)
    ax.text(sh, 172, " gün batımı", color=SUN, fontsize=6.5, va="top", alpha=0.85)
    ax2 = ax.twinx()
    temps = [h.temp for h in hrs]
    ax2.plot(xs, temps, color=TEMP, lw=2.2, zorder=5, solid_capstyle="round")
    lo, hi = min(temps), max(temps)
    span = max(hi - lo, 4)
    ax2.set_ylim(lo - span * 1.9, hi + span * 0.45)
    for h in hrs:
        if h.time.hour % 2 == 0:
            ax2.scatter([h.time.hour], [h.temp], s=14, color=TEMP, zorder=6)
            ax2.text(h.time.hour, h.temp + span * 0.12, f"{h.temp:.0f}°", color=TXT,
                     fontsize=7.5, ha="center", va="bottom", weight="bold", zorder=6)
    for a_ in (ax, ax2):
        a_.set_yticks([])
        for s in a_.spines.values():
            s.set_visible(False)
    ax.set_xticks(range(6, 24, 2))
    ax.set_xticklabels([f"{x:02d}" for x in range(6, 24, 2)], color=MUTED, fontsize=7.5)
    ax.tick_params(axis="x", length=0, pad=3)
    # hamle satırı
    gx = fig.add_axes([L + 0.045, 0.283, R - L - 0.09, 0.02], facecolor=CARD)
    gx.set_xlim(5.4, 23.6); gx.set_ylim(0, 1); gx.axis("off")
    for h in hrs:
        if h.time.hour % 2 == 0:
            gx.text(h.time.hour, 0.5, f"{h.gust:.0f}", color=_gust_color(h.gust),
                    fontsize=7, ha="center", va="center", weight="bold")

    # --- uyarılar + ekipman
    y_top = 0.235
    _box(fig, L, 0.045, cw, 0.205, ec=LINE)
    _box(fig, L + cw + 0.03, 0.045, cw, 0.205, ec=LINE)
    T(L + 0.03, y_top, "UYARILAR", color=MUTED, fontsize=9, weight="bold", va="center")
    T(L + cw + 0.06, y_top, "EKİPMAN", color=MUTED, fontsize=9, weight="bold", va="center")

    def bullets(x0, items, color, empty):
        y = y_top - 0.032
        if not items:
            T(x0, y, empty, color=FAINT, fontsize=9, va="top")
            return
        for it in items:
            wrapped = textwrap.wrap(it, 36)[:2]
            if y - 0.017 * len(wrapped) < 0.052:
                break
            T(x0, y, "•", color=color, fontsize=10, va="top", weight="bold")
            T(x0 + 0.022, y, "\n".join(wrapped), color=TXT, fontsize=8.2, va="top",
              linespacing=1.3)
            y -= 0.017 * len(wrapped) + 0.009

    warn = [w.split(": ", 1)[1] if ": " in w else w for w in rep.warnings]
    # aynı metni tekrar etme (sabah+akşam aynı uyarı)
    seen, uniq = set(), []
    for w, full in zip(warn, rep.warnings):
        if w not in seen:
            seen.add(w); uniq.append(full)
    bullets(L + 0.03, uniq, C["amber"], "Belirgin risk yok")
    bullets(L + cw + 0.06, rep.gear, C["green"], "—")

    T(0.5, 0.022, f"Open-Meteo · sürüş hissi {int(__import__('os').getenv('RIDE_SPEED_KMH', '60'))} km/h için hesaplandı",
      color=FAINT, fontsize=7, ha="center", va="center")

    fig.savefig(path, facecolor=BG, dpi=150)
    plt.close(fig)
    return path
