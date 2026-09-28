"""Сборка Android: на Windows запускаем flutter.bat, а не bash-скрипт «flutter» (WinError 193)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_android  # noqa: E402


class ToolTests(unittest.TestCase):
    def test_windows_prefers_batch_entry_point(self):
        found = {'flutter': r'C:\flutter\bin\flutter', 'flutter.bat': r'C:\flutter\bin\flutter.bat'}
        with patch.object(build_android.os, 'name', 'nt'), patch.object(build_android.shutil, 'which', found.get):
            self.assertEqual(build_android.tool('flutter'), r'C:\flutter\bin\flutter.bat')

    def test_version_for_stores(self):
        with patch.dict(build_android.os.environ, {'LOCAL_AI_ANDROID_BUILD_NUMBER': '42'}):
            name, code = build_android.app_version()
        self.assertRegex(name, r'^\d+\.\d+\.\d+$')
        self.assertEqual(code, '42')
        _, automatic = build_android.app_version()
        self.assertGreater(int(automatic), 800000)  # растёт с каждой сборкой


if __name__ == '__main__':
    unittest.main()
