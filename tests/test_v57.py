"""5.7: свернуть вкладку/сайт/браузер/себя, выключение и перезагрузка ПК, установка NDK для сборки Android."""
import io
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from src import power
from src.agent import LocalComputerAgent
from src.desktop.commands import DesktopCommands

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_android  # noqa: E402


class MinimizeMoreTests(unittest.TestCase):
    def make(self, process='chrome.exe', bridge=None):
        desktop = Mock(available=True)
        desktop.target_process.return_value = process
        browser = Mock()
        browser.bridge = bridge or Mock(connected=False)
        return desktop, DesktopCommands(desktop, browser=browser)

    def test_tab_minimizes_browser_window(self):
        desktop, commands = self.make()
        self.assertEqual(commands.handle('сверни вкладку', {}), 'Свернул окно браузера.')
        desktop.window.assert_called_once_with('minimize')

    def test_site_via_extension(self):
        bridge = Mock(connected=True)
        bridge.send.return_value = 1
        _, commands = self.make(bridge=bridge)
        with patch('src.app_control.minimize_application', return_value='youtube не запущено.'):
            self.assertEqual(commands.handle('сверни ютуб', {}), 'Сворачиваю ютуб.')
        bridge.send.assert_called_once_with('minimize', url='https://www.youtube.com')
        with patch('src.app_control.minimize_application') as app:
            commands.handle('сверни вкладку ютуб', {})
        app.assert_not_called()  # «вкладку …» — это сайт, не программа

    def test_site_by_window_title_on_windows(self):
        _, commands = self.make()
        from src import app_control
        with patch('src.app_control.minimize_application', return_value='ютуб не запущено.'), \
                patch('src.desktop.navigation.sys.platform', 'win32'), \
                patch.object(app_control, '_pids_by_names', return_value={1}), \
                patch.object(app_control, 'window_titles', return_value=[(11, 'Котики - YouTube - Google Chrome'),
                                                                        (12, 'Почта - Google Chrome')]), \
                patch.object(app_control, 'minimize_windows', side_effect=len) as minimize:
            self.assertEqual(commands.handle('сверни ютуб', {}), 'Сворачиваю ютуб.')
        minimize.assert_called_once_with([11])

    def test_self_and_explorer(self):
        from src import app_control
        with patch.object(app_control, 'minimize_self', return_value='Сворачиваюсь.'):
            self.assertEqual(app_control.minimize_application('себя'), 'Сворачиваюсь.')
        with patch.object(app_control.sys, 'platform', 'win32'), \
                patch.object(app_control, '_pids_by_names', return_value={5}) as pids, \
                patch.object(app_control, '_find_windows', return_value=[7]), \
                patch.object(app_control, 'minimize_windows', return_value=1):
            self.assertEqual(app_control.minimize_application('проводник'), 'Сворачиваю проводник')
        pids.assert_called_once_with({'explorer.exe'})


class PowerTests(unittest.TestCase):
    def setUp(self):
        self.done = []
        self.power = power.Power(runner=self.done.append)
        patcher = patch.object(power, 'power_command', return_value=['ok'])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_parse(self):
        self.assertEqual(power.parse('выключи компьютер'), ('shutdown', None))
        self.assertEqual(power.parse('Перезагрузи ПК через 10 минут'), ('restart', 10))
        self.assertEqual(power.parse('выключи компьютер через час'), ('shutdown', 60))
        self.assertEqual(power.parse('спящий режим'), ('sleep', None))
        self.assertEqual(power.parse('отмени выключение'), ('cancel',))
        self.assertIsNone(power.parse('выключи телеграм'))
        self.assertIsNone(power.parse('выключи звук'))

    def test_confirm_then_shutdown(self):
        with patch.object(power, 'GRACE_SECONDS', 0.05):
            self.assertEqual(self.power.handle('выключи компьютер', 'u', {'address': 'сэр'}),
                             'Выключить компьютер, сэр? Скажите «да».')
            self.assertTrue(self.power.awaiting('u'))
            self.assertIn('Сохраните работу', self.power.handle('да', 'u', {}))
            time.sleep(0.3)
        self.assertEqual(self.done, ['shutdown'])

    def test_no_and_cancel(self):
        self.power.handle('перезагрузи компьютер', 'u', {})
        self.assertEqual(self.power.handle('нет', 'u', {}), 'Хорошо, не перезагружаю.')
        self.power.handle('выключи компьютер через 30 минут', 'u', {})
        self.assertIn('Выключу компьютер в', self.power.handle('да', 'u', {}))
        self.assertEqual(self.power.handle('отмени выключение', 'u', {}), 'Выключение отменено.')
        self.assertEqual(self.done, [])

    def test_other_command_drops_question(self):
        self.power.handle('выключи компьютер', 'u', {})
        self.assertIsNone(self.power.handle('открой калькулятор', 'u', {}))
        self.assertFalse(self.power.awaiting('u'))

    def test_agent_routes_before_close_app(self):
        agent = LocalComputerAgent(Mock())
        agent.power = self.power
        self.assertIn('Скажите «да»', agent.process_command('Андрей, выключи компьютер', {}, owner='u'))
        self.assertTrue(agent.awaiting('u'))


class NdkTests(unittest.TestCase):
    def test_install_from_repository(self):
        sdk = Path(tempfile.mkdtemp())
        xml = b'''<sdk:sdk-repository xmlns:sdk="x"><remotePackage path="ndk;28.2.13676358"><archives>
            <archive><complete><url>android-ndk-r28c-windows.zip</url></complete><host-os>windows</host-os></archive>
            <archive><complete><url>android-ndk-r28c-linux.zip</url></complete><host-os>linux</host-os></archive>
            </archives></remotePackage></sdk:sdk-repository>'''
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('android-ndk-r28c/source.properties', 'Pkg.Revision = 28.2.13676358\n')
        requested = []

        def urlopen(url, timeout=None):
            requested.append(url)
            data = xml if url.endswith('.xml') else archive.getvalue()
            response = io.BytesIO(data)
            response.headers = {'Content-Length': str(len(data))}
            response.__enter__ = lambda self=response: self
            response.__exit__ = lambda *a: False
            return response
        with patch('urllib.request.urlopen', urlopen), patch.object(build_android.os, 'name', 'nt'):
            self.assertEqual(build_android.install_ndk(sdk, '28.2.13676358'), '28.2.13676358')
        self.assertTrue(requested[1].endswith('android-ndk-r28c-windows.zip'))
        self.assertTrue((sdk / 'ndk/28.2.13676358/source.properties').exists())
        self.assertEqual(build_android.installed_ndks(sdk), ['28.2.13676358'])

    def test_ensure_prefers_installed(self):
        sdk = Path(tempfile.mkdtemp())
        (sdk / 'ndk/27.0.12077973').mkdir(parents=True)
        (sdk / 'ndk/27.0.12077973/source.properties').write_text('x')
        with patch.object(build_android, 'sdk_dir', return_value=sdk), \
                patch.object(build_android, 'required_ndk', return_value='28.2.13676358'), \
                patch.object(build_android, 'install_ndk', side_effect=OSError('offline')):
            self.assertEqual(build_android.ensure_ndk('flutter'), '27.0.12077973')
        with patch.object(build_android, 'sdk_dir', return_value=sdk), \
                patch.object(build_android, 'required_ndk', return_value='27.0.12077973'):
            self.assertEqual(build_android.ensure_ndk('flutter'), '27.0.12077973')


if __name__ == '__main__':
    unittest.main()
