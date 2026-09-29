"""Темы «Гжель» и «Славянская»: есть на ПК, в схеме настроек телефона и на Android, орнаменты на месте."""
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from src.settings_schema import THEMES as SCHEMA_THEMES
from src.storage import THEMES

ROOT = Path(__file__).resolve().parents[1]


class FolkThemeTests(unittest.TestCase):
    def test_registered_everywhere(self):
        for theme in ('gzhel', 'slavic'):
            self.assertIn(theme, THEMES)
            self.assertIn(theme, dict(SCHEMA_THEMES))
            self.assertIn(f"id: '{theme}'", (ROOT / 'static/core.js').read_text(encoding='utf-8'))
            self.assertIn(f"'{theme}': Palette('{theme}'", (ROOT / 'android_client/lib/theme.dart').read_text(encoding='utf-8'))

    def test_ornaments_exist_and_are_valid_svg(self):
        css = (ROOT / 'static/themes.css').read_text(encoding='utf-8')
        names = set(re.findall(r'/static/ornaments/([\w-]+\.svg)', css))
        self.assertGreaterEqual(len(names), 6)
        for name in names:
            root = ET.parse(ROOT / 'static/ornaments' / name).getroot()
            self.assertTrue(root.tag.endswith('svg'), name)

    def test_particles(self):
        motion = (ROOT / 'static/motion.js').read_text(encoding='utf-8')
        self.assertIn("theme === 'gzhel'", motion)
        self.assertIn("theme === 'slavic'", motion)


if __name__ == '__main__':
    unittest.main()
