"""Генератор орнаментов тем «Гжель» и «Славянская»."""
import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / 'static' / 'ornaments'


def crescent(r, span=58, depth=1.55):
    """Мазок-полумесяц: толстый посередине, сходит на нет к концам (как кистевой мазок гжели).

    depth — толщина мазка посередине в долях радиуса (по умолчанию ~0.3 r)."""
    a = math.radians(span)
    x, y = r * math.sin(a), -r * math.cos(a)
    t = r * (0.3 if depth >= 1 else depth) * (1.25 if depth > 1.6 else 1)
    top = -r + t                      # нижняя кромка мазка посередине
    c = (x * x + y * y - top * top) / (2 * (y - top))  # центр окружности через три точки (на оси y)
    big = abs(top - c)
    sweep = 0 if top < y else 1
    return (f'M{-x:.1f} {y:.1f}A{r} {r} 0 0 1 {x:.1f} {y:.1f}'
            f'A{big:.1f} {big:.1f} 0 0 {sweep} {-x:.1f} {y:.1f}Z')


GZ_ROSE = ((9, 2, 20, 62), (17, 3, 70, 44), (27, 4, 15, 36), (39, 5, 50, 30), (52, 3, 150, 34))


def rose(fill, core, rings=GZ_ROSE, scale=1.0, depth=1.55, fill2=None, cup=True):
    """Роза из мазков: кольца лепестков с просветами, внизу — широкая «чаша»."""
    parts = []
    for k, (r, n, offset, span) in enumerate(rings):
        d = crescent(r, span, depth)
        color = fill2 if fill2 and k % 2 else fill
        for i in range(n):
            parts.append(f'<path d="{d}" fill="{color}" transform="rotate({offset + i * 360 / n:.1f})"/>')
    if cup:
        big = rings[-1][0] + 8
        parts.append(f'<path d="{crescent(big, 62, 1.9)}" fill="{fill}" transform="rotate(180)"/>')
        parts.append(f'<path d="{crescent(big - 12, 48, 1.8)}" fill="{fill2 or fill}" opacity=".85" transform="rotate(180)"/>')
    parts.append(f'<circle r="5.5" fill="{core}"/>')
    return f'<g transform="scale({scale})">' + ''.join(parts) + '</g>'


def leaf(fill, length=70, width=16):
    w = width
    return f'<path d="M0 0C{length*.25:.0f} {-w} {length*.7:.0f} {-w*.9:.0f} {length} 0C{length*.7:.0f} {w*.35:.0f} {length*.25:.0f} {w*.4:.0f} 0 0Z" fill="{fill}"/>'


def drops(fill, n, r0, step, size):
    return ''.join(f'<circle cx="{r0 + i*step}" cy="0" r="{max(1.2, size - i*.7):.1f}" fill="{fill}"/>' for i in range(n))


# ---------- ГЖЕЛЬ ----------
GZ_DEFS = '''<defs>
<linearGradient id="b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0b2a86"/><stop offset=".55" stop-color="#2459cc"/><stop offset="1" stop-color="#8fb2f0" stop-opacity=".55"/></linearGradient>
<linearGradient id="l" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#0b2a86"/><stop offset=".6" stop-color="#2a60d0"/><stop offset="1" stop-color="#9dbcf3" stop-opacity=".5"/></linearGradient>
<radialGradient id="c"><stop offset="0" stop-color="#061d66"/><stop offset="1" stop-color="#1f4fc0"/></radialGradient>
</defs>'''


def gzhel_spray():
    stems = ('<g fill="none" stroke="#1d4bbd" stroke-linecap="round">'
             '<path d="M300 300C250 250 190 215 120 190" stroke-width="3.2"/>'
             '<path d="M300 300C282 225 262 160 214 96" stroke-width="3"/>'
             '<path d="M232 244C212 200 178 170 150 150" stroke-width="2"/>'
             '<path d="M120 190C96 182 78 168 66 150" stroke-width="1.6"/>'
             '<path d="M214 96C206 76 206 58 214 40" stroke-width="1.6"/></g>')
    leaves = ''.join(f'<g transform="translate({x} {y}) rotate({a})">{leaf("url(#l)", ln, w)}</g>' for x, y, a, ln, w in (
        (250, 252, 200, 64, 15), (246, 238, 245, 56, 13), (200, 222, 170, 58, 14), (268, 200, 250, 60, 14),
        (236, 150, 215, 52, 12), (240, 142, 285, 46, 11), (160, 196, 150, 44, 11), (180, 212, 215, 42, 10)))
    grass = ''.join(f'<g transform="translate({x} {y}) rotate({a})">{drops("#1d4bbd", 4, 10, 9, 3.4)}</g>' for x, y, a in (
        (66, 150, 225), (214, 40, 260), (150, 150, 200), (300, 300, 190), (300, 300, 245)))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 320">{GZ_DEFS}{stems}{leaves}{grass}'
            f'<g transform="translate(120 190)">{rose("url(#b)", "url(#c)", scale=.95)}</g>'
            f'<g transform="translate(214 96)">{rose("url(#b)", "url(#c)", rings=((8, 2, 0, 60), (15, 3, 50, 44), (24, 4, 20, 36), (34, 3, 110, 36)), scale=.9)}</g>'
            f'<g transform="translate(150 150)">{rose("url(#b)", "url(#c)", rings=((7, 2, 0, 60), (14, 3, 40, 44), (21, 2, 100, 40)), cup=False)}</g>'
            '</svg>')


def gzhel_orb():
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-70 -70 140 140">{GZ_DEFS}'
            + ''.join(f'<g transform="rotate({a}) translate(0 -52)">{drops("#2459cc", 3, -9, 9, 2.6)}</g>' for a in range(0, 360, 45))
            + rose('url(#b)', 'url(#c)', scale=.78) + '</svg>')


def gzhel_band():
    # Фестон: полукружья с каплями — кайма гжельской тарелки.
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 16" width="48" height="16">'
            '<path d="M0 0H48V3Q36 14 24 3Q12 14 0 3Z" fill="#1d4bbd"/>'
            '<path d="M0 3Q12 14 24 3Q36 14 48 3" fill="none" stroke="#0b2a86" stroke-width="1.2"/>'
            '<circle cx="12" cy="13" r="1.7" fill="#2459cc"/><circle cx="36" cy="13" r="1.7" fill="#2459cc"/>'
            '<circle cx="24" cy="1.5" r="1" fill="#fff" opacity=".8"/></svg>')


def gzhel_petal():
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="-40 -40 80 80">' + GZ_DEFS
            + f'<path d="{crescent(34)}" fill="url(#b)"/></svg>')


# ---------- ХОХЛОМА ----------
KH_DEFS = '''<defs>
<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff0b0"/><stop offset=".35" stop-color="#f0c55a"/><stop offset=".7" stop-color="#c88a22"/><stop offset="1" stop-color="#7a4a0e"/></linearGradient>
<radialGradient id="r" cx=".35" cy=".3"><stop offset="0" stop-color="#ff8a6a"/><stop offset=".35" stop-color="#e0321f"/><stop offset="1" stop-color="#7a0b07"/></radialGradient>
<radialGradient id="o" cx=".38" cy=".32"><stop offset="0" stop-color="#ffe9a8"/><stop offset=".45" stop-color="#e3a93c"/><stop offset="1" stop-color="#8a560f"/></radialGradient>
</defs>'''


def curl(x, y, size, turn, width=2.2):
    """Завиток «травки»: сходящаяся спираль."""
    pts = []
    for i in range(46):
        t = i / 45 * math.pi * 2.3
        rad = size * (1 - i / 52)
        pts.append((x + rad * math.cos(t * turn), y + rad * math.sin(t * turn)))
    d = 'M' + ' L'.join(f'{px:.1f} {py:.1f}' for px, py in pts)
    return f'<path d="{d}" fill="none" stroke="url(#g)" stroke-width="{width}" stroke-linecap="round"/>'


def berry_cluster(x, y, r=9):
    out = []
    for dx, dy in ((0, 0), (r * 1.7, r * .5), (r * .6, r * 1.7), (-r * 1.1, r * 1.2), (r * 1.9, r * 2.1)):
        out.append(f'<circle cx="{x+dx:.1f}" cy="{y+dy:.1f}" r="{r}" fill="url(#r)"/>'
                   f'<circle cx="{x+dx-r*.35:.1f}" cy="{y+dy-r*.38:.1f}" r="{r*.22:.1f}" fill="#ffe6b0" opacity=".85"/>'
                   f'<circle cx="{x+dx+r*.3:.1f}" cy="{y+dy+r*.35:.1f}" r="{r*.14:.1f}" fill="#2a0503"/>')
    return ''.join(out)


def kh_leaf(x, y, a, ln, w):
    return (f'<g transform="translate({x} {y}) rotate({a})">{leaf("url(#g)", ln, w)}'
            f'<path d="M4 0Q{ln*.5:.0f} {-w*.2:.1f} {ln*.9:.0f} 0" stroke="#7a2a08" stroke-width="1.3" fill="none"/>'
            + ''.join(f'<path d="M{ln*k:.0f} {-w*.12:.1f}l{ln*.12:.0f} {-w*.45:.1f}" stroke="#9a3a0a" stroke-width="1" fill="none"/>' for k in (.3, .5, .7))
            + '</g>')


def khokhloma():
    stems = ('<g fill="none" stroke="url(#g)" stroke-linecap="round">'
             '<path d="M360 360C300 300 240 270 150 250C110 240 80 210 76 170" stroke-width="4"/>'
             '<path d="M360 360C330 280 300 210 250 150C225 120 210 90 214 60" stroke-width="3.6"/>'
             '<path d="M270 300C250 250 215 220 180 205" stroke-width="2.4"/></g>')
    curls = curl(76, 150, 20, 1) + curl(214, 44, 18, -1) + curl(172, 196, 13, 1, 1.8) + curl(118, 262, 12, -1, 1.6) + curl(300, 196, 14, 1, 1.8)
    leaves = ''.join(kh_leaf(*p) for p in (
        (300, 318, 200, 70, 17), (286, 296, 250, 60, 15), (222, 268, 175, 64, 16), (250, 252, 215, 50, 13),
        (284, 232, 250, 62, 15), (256, 170, 215, 56, 14), (262, 164, 290, 50, 12), (160, 254, 160, 50, 13),
        (112, 238, 230, 48, 12), (230, 120, 250, 44, 11)))
    # «Кудрина» — золотой цветок-завиток с красной серединой
    flower = ('<g transform="translate(150 250)">' + rose('url(#g)', 'url(#r)', rings=((9, 2, 0, 62), (17, 3, 60, 46), (27, 4, 20, 38), (39, 5, 45, 32)), depth=1.7, fill2='url(#r)') + '</g>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 380 380">{KH_DEFS}{stems}{curls}{leaves}{flower}'
            f'{berry_cluster(224, 200, 9)}{berry_cluster(196, 88, 8)}{berry_cluster(318, 250, 7)}</svg>')


def kh_orb():
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-70 -70 140 140">{KH_DEFS}'
            + ''.join(f'<g transform="rotate({a})"><path d="{crescent(58, 20, 1.3)}" fill="url(#g)" opacity=".9"/></g>' for a in range(0, 360, 30))
            + rose('url(#g)', 'url(#r)', rings=((9, 2, 0, 62), (17, 3, 60, 46), (27, 4, 20, 38), (38, 5, 45, 32)), depth=1.7, scale=.9, fill2='url(#r)') + '</svg>')


# Вышивка крестиком: ромб-«земля» с засеянными полями и крестики-обереги между ромбами.
MOTIF = [
    '.......R.......',
    '......R.R......',
    '.....R.G.R.....',
    '....R.GGG.R....',
    '...R.G.R.G.R...',
    '..R.G.RRR.G.R..',
    '.R.G.RR.RR.G.R.',
    'R.G.RR.G.RR.G.R',
]
MOTIF = MOTIF + MOTIF[-2::-1]
CROSS = ['.G.', 'GGG', '.G.']


def stitch_band(cell=3):
    width = 15 + 5
    rows = []
    rows.append(''.join('R' if i % 2 == 0 else 'G' for i in range(width)))
    rows.append('.' * width)
    for r in range(15):
        mid = CROSS[r - 6] if 6 <= r <= 8 else '...'
        rows.append(MOTIF[r] + '.' + mid + '.')
    rows.append('.' * width)
    rows.append(''.join('G' if i % 2 == 0 else 'R' for i in range(width)))
    colors = {'R': '#d0302a', 'G': '#e9b949'}
    rects = []
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in colors:
                # стежок-крестик: две диагонали
                x0, y0 = x * cell, y * cell
                rects.append(f'<path d="M{x0+.4} {y0+.4}l{cell-.8} {cell-.8}M{x0+cell-.4} {y0+.4}l{-(cell-.8)} {cell-.8}" stroke="{colors[ch]}" stroke-width="1.35" stroke-linecap="round"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width*cell} {len(rows)*cell}" width="{width*cell}" height="{len(rows)*cell}">'
            + ''.join(rects) + '</svg>')


FILES = {'gzhel-spray.svg': gzhel_spray(), 'gzhel-orb.svg': gzhel_orb(), 'gzhel-band.svg': gzhel_band(),
         'gzhel-petal.svg': gzhel_petal(), 'khokhloma.svg': khokhloma(), 'khokhloma-orb.svg': kh_orb(),
         'stitch-band.svg': stitch_band()}
for name, svg in FILES.items():
    (OUT / name).write_text(svg + '\n', encoding='utf-8')
    print(name, len(svg))
