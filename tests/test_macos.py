"""macOS: клавиши через Quartz, приложения через open/osascript, автозапуск, llama.cpp для Mac.

Quartz и AppKit подменяются заглушками, поэтому тесты идут на любой системе.
"""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class FakeQuartz(types.ModuleType):
    kCGHIDEventTap = 0
    kCGEventSourceStateHIDSystemState = 1

    def __init__(self):
        super().__init__('Quartz')
        self.posted = []

    def CGEventCreateKeyboardEvent(self, source, code, down):
        return {'code': code, 'down': down, 'flags': 0, 'text': None}

    def CGEventSetFlags(self, event, flags):
        event['flags'] = flags

    def CGEventKeyboardSetUnicodeString(self, event, length, text):
        event['text'] = text

    def CGEventPost(self, tap, event):
        self.posted.append(event)

    def CGEventSourceFlagsState(self, state):
        return 0


class MacKeysTests(unittest.TestCase):
    def setUp(self):
        self.quartz = FakeQuartz()
        patcher = patch.dict(sys.modules, {'Quartz': self.quartz})
        patcher.start()
        self.addCleanup(patcher.stop)
        from src.desktop import macapi
        self.mac = macapi

    def pressed(self):
        return [(e['code'], e['flags']) for e in self.quartz.posted if e['down']]

    def test_ctrl_becomes_command(self):
        self.mac.hotkey('ctrl', 'v')
        self.assertEqual(self.pressed(), [(self.mac.KEYCODES['v'], self.mac.MODIFIER_FLAGS['cmd'])])

    def test_windows_combos(self):
        self.mac.hotkey('win', 'd')  # «Покажи рабочий стол»
        self.mac.hotkey('ctrl', 'y')  # «Повтори»
        cmd, shift = self.mac.MODIFIER_FLAGS['cmd'], self.mac.MODIFIER_FLAGS['shift']
        self.assertEqual(self.pressed(), [(self.mac.KEYCODES['f3'], cmd), (self.mac.KEYCODES['z'], cmd | shift)])

    def test_shift_enter_in_messengers(self):
        self.mac.type_unicode('привет\nкак дела', newline=('shift', 'enter'))
        texts = [e['text'] for e in self.quartz.posted if e['down'] and e['text']]
        self.assertEqual(texts, ['привет', 'как дела'])
        self.assertIn((self.mac.KEYCODES['enter'], self.mac.MODIFIER_FLAGS['shift']), self.pressed())

    def test_long_text_in_chunks(self):
        self.mac.type_unicode('а' * 40)
        self.assertEqual([len(e['text']) for e in self.quartz.posted if e['down']], [16, 16, 8])

    def test_unknown_key(self):
        with self.assertRaises(ValueError):
            self.mac.hotkey('ctrl', 'нет')


@patch('src.macos.subprocess.run')
class MacAppsTests(unittest.TestCase):
    def test_names(self, run):
        from src.macos import mac_name
        self.assertEqual(mac_name('телеграм'), 'Telegram')
        self.assertEqual(mac_name('калькулятор'), 'Calculator')
        self.assertEqual(mac_name('ворд'), 'Microsoft Word')
        self.assertEqual(mac_name('хром'), 'Google Chrome')
        self.assertEqual(mac_name('приложение Notion'), 'Notion')

    def test_launch_with_open(self, run):
        from src import app_control
        run.return_value = Mock(returncode=0, stdout='false')
        with patch.object(sys, 'platform', 'darwin'):
            self.assertEqual(app_control.launch('телеграм'), 'Открываю телеграм')
        run.assert_called_with(['open', '-a', 'Telegram'], capture_output=True, text=True, timeout=15)

    def test_close_asks_app_to_quit(self, run):
        from src import app_control
        run.return_value = Mock(returncode=0, stdout='true')
        with patch.object(sys, 'platform', 'darwin'):
            self.assertEqual(app_control.close_application('Safari'), 'Закрываю Safari')
        self.assertIn('tell application "Safari" to quit', run.call_args.args[0][2])
        with patch.object(sys, 'platform', 'darwin'):
            self.assertIn('Не удалось', app_control.close_application('finder'))


class MacSystemTests(unittest.TestCase):
    def test_autostart_launch_agent(self):
        from src import autostart
        with tempfile.TemporaryDirectory() as temp, patch.object(sys, 'platform', 'darwin'), \
                patch.object(autostart, 'LAUNCH_AGENT', Path(temp) / 'agent.plist'):
            autostart.configure(True)
            self.assertTrue(autostart.enabled())
            import plistlib
            data = plistlib.loads(autostart.LAUNCH_AGENT.read_bytes())
            self.assertTrue(data['RunAtLoad'])
            self.assertIn('--minimized', data['ProgramArguments'])
            autostart.configure(False)
            self.assertFalse(autostart.enabled())

    def test_llama_mac_asset(self):
        from src import model_downloader as md
        assets = [{'name': 'llama-b7000-bin-win-cpu-x64.zip'}, {'name': f'llama-b7000-bin-macos-{md.MAC_ARCH}.zip'},
                  {'name': 'llama-b7000-bin-macos-x64-old.zip'}]
        self.assertEqual(md.pick_asset(assets, 'cpu', 'darwin')['name'], f'llama-b7000-bin-macos-{md.MAC_ARCH}.zip')
        self.assertEqual(md.pick_asset(assets, 'cpu', 'win32')['name'], 'llama-b7000-bin-win-cpu-x64.zip')

    def test_llama_tar_install_sets_exec_bit(self):
        import io
        import tarfile
        from src import model_downloader as md
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'llama.tar.gz'
            with tarfile.open(archive, 'w:gz') as tf:
                data = b'#!/bin/sh\n'
                info = tarfile.TarInfo('build/bin/llama-server')
                info.size, info.mode = len(data), 0o644
                tf.addfile(info, io.BytesIO(data))
            with patch('src.brain.local_llm.BINARY', 'llama-server'), patch.object(md.sys, 'platform', 'darwin'):
                target = md.install_llama_zip(Path(temp) / 'root', archive)
            binary = next(target.rglob('llama-server'))
            self.assertTrue(binary.stat().st_mode & 0o100)

    def test_data_folder(self):
        from src import storage
        with patch.object(sys, 'platform', 'darwin'), patch.dict('os.environ', {}, clear=False) as env:
            env.pop('LOCAL_AI_DATA_DIR', None)
            self.assertEqual(storage.data_root().parts[-3:], ('Library', 'Application Support', 'LocalAIAgent'))


class IPhoneTests(unittest.TestCase):
    def setUp(self):
        from app import create_app
        from src.storage import Store
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.agent = Mock()
        self.agent.process_command.return_value = 'Курс доллара — 81 рубль.'
        self.app = create_app(self.store, Mock(status=Mock(return_value={})), self.agent, license=Mock(is_premium=lambda: True))
        self.client = self.app.test_client()
        self.token = self.store.meta('pairing_token')

    def tearDown(self):
        self.temp.cleanup()

    def test_qr_contains_pairing_link(self):
        response = self.client.get('/api/connection/qr', headers={'X-Agent-Token': self.token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/svg+xml')
        self.assertIn(b'<svg', response.data)
        self.assertEqual(self.client.get('/api/connection/qr').status_code, 401)

    def test_siri_shortcut(self):
        response = self.client.post('/api/siri', json={'text': 'какой курс доллара'}, headers={'X-Agent-Token': self.token})
        self.assertEqual(response.get_json()['response'], 'Курс доллара — 81 рубль.')
        args = self.agent.process_command.call_args
        self.assertEqual(args.args[0], 'какой курс доллара')
        self.assertEqual(args.kwargs['owner'], 'device:siri')
        self.assertEqual(self.client.post('/api/siri', json={'text': 'x'}).status_code, 401)
        self.assertEqual(self.client.post('/api/siri', json={}, headers={'X-Agent-Token': self.token}).status_code, 400)

    def test_ios_meta_tags(self):
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('apple-mobile-web-app-capable', html)
        self.assertIn('apple-touch-icon', html)


if __name__ == '__main__':
    unittest.main()
