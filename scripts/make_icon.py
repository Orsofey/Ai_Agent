"""Иконка «Стекло»: светлая стеклянная плашка и радужная стеклянная сфера."""
import glob, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image

R = Path(__file__).resolve().parents[1]
S = R / 'build' / 'icon'
S.mkdir(parents=True, exist_ok=True)

BG_DEFS = '''
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fdf9f4"/><stop offset=".55" stop-color="#f1ebe4"/><stop offset="1" stop-color="#e9e3f4"/></linearGradient>
<radialGradient id="b1" cx=".14" cy=".12" r=".55"><stop offset="0" stop-color="#ffc08e" stop-opacity=".85"/><stop offset="1" stop-color="#ffc08e" stop-opacity="0"/></radialGradient>
<radialGradient id="b2" cx=".92" cy=".18" r=".5"><stop offset="0" stop-color="#d8a8ff" stop-opacity=".7"/><stop offset="1" stop-color="#d8a8ff" stop-opacity="0"/></radialGradient>
<radialGradient id="b3" cx=".85" cy=".95" r=".55"><stop offset="0" stop-color="#8fd3ff" stop-opacity=".8"/><stop offset="1" stop-color="#8fd3ff" stop-opacity="0"/></radialGradient>
<radialGradient id="b4" cx=".08" cy=".92" r=".45"><stop offset="0" stop-color="#b6f0c4" stop-opacity=".75"/><stop offset="1" stop-color="#b6f0c4" stop-opacity="0"/></radialGradient>
<linearGradient id="rim" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".95"/><stop offset=".4" stop-color="#fff" stop-opacity=".25"/><stop offset=".75" stop-color="#fff" stop-opacity=".1"/><stop offset="1" stop-color="#fff" stop-opacity=".7"/></linearGradient>
'''

def sphere(cx, cy, r):
    return f'''
<defs>
 <clipPath id="ball"><circle cx="{cx}" cy="{cy}" r="{r}"/></clipPath>
 <radialGradient id="core" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#ffffff"/><stop offset=".7" stop-color="#ece6ff"/><stop offset="1" stop-color="#d2c6ff"/></radialGradient>
 <radialGradient id="c1" cx=".26" cy=".34" r=".42"><stop offset="0" stop-color="#ffa864"/><stop offset="1" stop-color="#ffa864" stop-opacity="0"/></radialGradient>
 <radialGradient id="c2" cx=".78" cy=".28" r=".44"><stop offset="0" stop-color="#4cc4ff"/><stop offset="1" stop-color="#4cc4ff" stop-opacity="0"/></radialGradient>
 <radialGradient id="c3" cx=".72" cy=".78" r=".46"><stop offset="0" stop-color="#9a6bff"/><stop offset="1" stop-color="#9a6bff" stop-opacity="0"/></radialGradient>
 <radialGradient id="c4" cx=".26" cy=".78" r=".42"><stop offset="0" stop-color="#ff5fae"/><stop offset="1" stop-color="#ff5fae" stop-opacity="0"/></radialGradient>
 <radialGradient id="c5" cx=".5" cy=".52" r=".32"><stop offset="0" stop-color="#7cf0b2" stop-opacity=".8"/><stop offset="1" stop-color="#7cf0b2" stop-opacity="0"/></radialGradient>
 <radialGradient id="fres" cx=".5" cy=".5" r=".5"><stop offset=".6" stop-color="#fff" stop-opacity="0"/><stop offset=".86" stop-color="#fff" stop-opacity=".35"/><stop offset="1" stop-color="#fff" stop-opacity=".9"/></radialGradient>
 <radialGradient id="dark" cx=".62" cy=".7" r=".6"><stop offset=".55" stop-color="#3c1e9a" stop-opacity="0"/><stop offset="1" stop-color="#3c1e9a" stop-opacity=".32"/></radialGradient>
 <filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="{r*0.055:.1f}"/></filter>
 <filter id="shadow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="{r*0.16:.1f}"/></filter>
</defs>
<ellipse cx="{cx}" cy="{cy + r*0.98:.1f}" rx="{r*0.82:.1f}" ry="{r*0.2:.1f}" fill="#7a5cff" opacity=".42" filter="url(#shadow)"/>
<ellipse cx="{cx + r*0.1:.1f}" cy="{cy + r*1.0:.1f}" rx="{r*0.45:.1f}" ry="{r*0.1:.1f}" fill="#ff7ab8" opacity=".35" filter="url(#shadow)"/>
<g clip-path="url(#ball)">
 <rect x="{cx-r}" y="{cy-r}" width="{2*r}" height="{2*r}" fill="url(#core)"/>
 <rect x="{cx-r}" y="{cy-r}" width="{2*r}" height="{2*r}" fill="url(#c1)"/>
 <rect x="{cx-r}" y="{cy-r}" width="{2*r}" height="{2*r}" fill="url(#c2)"/>
 <rect x="{cx-r}" y="{cy-r}" width="{2*r}" height="{2*r}" fill="url(#c3)"/>
 <rect x="{cx-r}" y="{cy-r}" width="{2*r}" height="{2*r}" fill="url(#c4)"/>
 <rect x="{cx-r}" y="{cy-r}" width="{2*r}" height="{2*r}" fill="url(#c5)"/>
 <rect x="{cx-r}" y="{cy-r}" width="{2*r}" height="{2*r}" fill="url(#dark)"/>
 <rect x="{cx-r}" y="{cy-r}" width="{2*r}" height="{2*r}" fill="url(#fres)"/>
 <ellipse cx="{cx - r*0.3:.1f}" cy="{cy - r*0.52:.1f}" rx="{r*0.42:.1f}" ry="{r*0.2:.1f}" fill="#fff" opacity=".92" filter="url(#soft)" transform="rotate(-24 {cx - r*0.3:.1f} {cy - r*0.52:.1f})"/>
 <ellipse cx="{cx + r*0.12:.1f}" cy="{cy + r*0.8:.1f}" rx="{r*0.46:.1f}" ry="{r*0.14:.1f}" fill="#fff" opacity=".6" filter="url(#soft)"/>
</g>
<circle cx="{cx}" cy="{cy}" r="{r - r*0.008:.1f}" fill="none" stroke="url(#rim)" stroke-width="{r*0.025:.1f}"/>
'''

def full_icon():
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
<defs>{BG_DEFS}<clipPath id="tile"><rect x="40" y="40" width="944" height="944" rx="236"/></clipPath>
<filter id="tileshadow" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="14"/></filter></defs>
<rect x="56" y="70" width="912" height="912" rx="228" fill="#5a46b4" opacity=".18" filter="url(#tileshadow)"/>
<g clip-path="url(#tile)">
 <rect width="1024" height="1024" fill="url(#bg)"/>
 <rect width="1024" height="1024" fill="url(#b1)"/><rect width="1024" height="1024" fill="url(#b2)"/>
 <rect width="1024" height="1024" fill="url(#b3)"/><rect width="1024" height="1024" fill="url(#b4)"/>
 {sphere(512, 488, 300)}
</g>
<rect x="42" y="42" width="940" height="940" rx="234" fill="none" stroke="url(#rim)" stroke-width="5"/>
</svg>'''

def background_only():
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><defs>{BG_DEFS}</defs>
<rect width="1024" height="1024" fill="url(#bg)"/><rect width="1024" height="1024" fill="url(#b1)"/><rect width="1024" height="1024" fill="url(#b2)"/>
<rect width="1024" height="1024" fill="url(#b3)"/><rect width="1024" height="1024" fill="url(#b4)"/></svg>'''

def foreground_only():   # адаптивная иконка Android: сфера в безопасной зоне (66%)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><defs>{BG_DEFS}</defs>{sphere(512, 500, 250)}</svg>'

exe = glob.glob('/opt/pw-browsers/chromium-*/chrome-linux*/chrome')[0]
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=exe); pg = b.new_page()
    def render(markup, size, out):
        pg.set_viewport_size({'width': size, 'height': size})
        pg.set_content('<html><body style="margin:0;background:transparent">' +
                       markup.replace('<svg ', f'<svg width="{size}" height="{size}" style="display:block" ', 1) + '</body></html>')
        pg.screenshot(path=str(out), omit_background=True)
    icon = full_icon()
    (R / 'static/icon.svg').write_text(icon, encoding='utf-8')
    render(icon, 1024, R / 'static/icon.png')
    render(icon, 512, R / 'static/icon-512.png')
    render(icon, 192, R / 'static/icon-192.png')
    render(icon, 1024, R / 'android_client/assets/icon.png')
    render(background_only(), 1024, R / 'android_client/assets/icon-background.png')
    render(foreground_only(), 1024, R / 'android_client/assets/icon-foreground.png')
    for n in (16, 32, 48, 128):
        render(icon, n, R / f'browser_extension/icons/icon{n}.png')
    for n in (16, 24, 32, 48, 64, 128, 256):
        render(icon, n, S / f'ico{n}.png')
    b.close()
imgs = [Image.open(S / f'ico{n}.png').convert('RGBA') for n in (256, 128, 64, 48, 32, 24, 16)]
imgs[0].save(R / 'static/icon.ico', sizes=[(i.width, i.height) for i in imgs], append_images=imgs[1:])
print(Image.open(R / 'static/icon.ico').ico.sizes())
