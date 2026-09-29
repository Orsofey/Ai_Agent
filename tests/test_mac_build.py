"""Сборка для macOS: подпись изнутри наружу, обязательная проверка, самотест."""
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MacBuildTests(unittest.TestCase):
    def test_package_script(self):
        text = (ROOT / 'packaging/macos/package.sh').read_text(encoding='utf-8')
        self.assertIn('sort -z', text)
        self.assertIn('--self-test', text)
        self.assertNotIn('&& echo "Подпись проверена"', text)  # под set -e проверка должна валить сборку

    @unittest.skipIf(sys.platform == 'win32' or not shutil.which('bash'),
                     'синтаксис .sh проверяется на macOS/Linux (в Windows «bash» — это WSL, часто без Linux)')
    def test_shell_syntax(self):
        for script in ('packaging/macos/package.sh', 'BUILD_MAC.sh'):
            self.assertEqual(subprocess.run(['bash', '-n', str(ROOT / script)]).returncode, 0, script)

    def test_spec_version_from_app(self):
        spec = (ROOT / 'LocalAIAgent.spec').read_text(encoding='utf-8')
        self.assertNotIn("'5.0'", spec)
        self.assertRegex((ROOT / 'app.py').read_text(encoding='utf-8'), re.compile(r"^VERSION = '[\d.]+'", re.M))

    def test_main_has_self_test(self):
        self.assertIn("'--self-test' in sys.argv", (ROOT / 'main.py').read_text(encoding='utf-8'))

    def test_workflow_checks_dmg(self):
        text = (ROOT / '.github/workflows/build-mac.yml').read_text(encoding='utf-8')
        self.assertIn('--self-test', text)
        self.assertIn('.sha256', text)


if __name__ == '__main__':
    unittest.main()
