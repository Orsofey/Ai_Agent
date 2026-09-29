"""Фирменная тема AI Agent — по умолчанию, со своими шрифтами (офлайн) и иконкой-волной."""
import re
import unittest
from pathlib import Path

from src.settings_schema import THEMES as SCHEMA_THEMES
from src.storage import DEFAULTS, THEMES

ROOT = Path(__file__).resolve().parents[1]


class BrandThemeTests(unittest.TestCase):
    def test_default_everywhere(self):
        self.assertEqual(DEFAULTS['theme'], 'brand')
        self.assertEqual(THEMES[0], 'brand')
        self.assertEqual(SCHEMA_THEMES[0][0], 'brand')
        for page in ('index.html', 'settings.html'):
            self.assertIn("|| 'brand'", (ROOT / 'templates' / page).read_text(encoding='utf-8'))
        self.assertIn("paletteOf('brand')", (ROOT / 'android_client/lib/main.dart').read_text(encoding='utf-8'))

    def test_brand_colors_and_no_glow(self):
        css = (ROOT / 'static/themes.css').read_text(encoding='utf-8')
        block = re.search(r'\[data-theme="brand"\] \{(.*?)\n\}', css, re.S).group(1)
        for token in ('#0E0F12', '#1A1C21', '#2E323A', '#9398A5', '#4C7DFF'):
            self.assertIn(token, block)
        self.assertIn('--on-accent: #0E0F12', block)   # текст на синем — Ink
        self.assertIn('--shadow: none', block)
        self.assertIn('#C8F53C', css)                    # курсор ▮

    def test_fonts_bundled_with_license(self):
        css = (ROOT / 'static/themes.css').read_text(encoding='utf-8')
        for font in re.findall(r"url\('/static/fonts/([\w-]+\.ttf)'\)", css):
            self.assertTrue((ROOT / 'static/fonts' / font).stat().st_size > 10_000, font)
        for lic in ('Tektur-OFL.txt', 'JetBrainsMono-OFL.txt'):
            self.assertTrue((ROOT / 'static/fonts' / lic).exists())

    def test_icon_is_the_wave(self):
        svg = (ROOT / 'static/icon.svg').read_text(encoding='utf-8')
        self.assertIn('rx="5.5" fill="#4C7DFF"', svg)
        self.assertEqual(svg.count('fill="#0E0F12"'), 5)
        from PIL import Image
        with Image.open(ROOT / 'static/icon-512.png') as image:
            self.assertEqual(image.getpixel((256, 40))[:3], (0x4C, 0x7D, 0xFF))
        with Image.open(ROOT / 'static/icon.ico') as ico:
            self.assertIn((16, 16), ico.ico.sizes())


if __name__ == '__main__':
    unittest.main()
