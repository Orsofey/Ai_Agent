"""6.2: «Стекло» по умолчанию, автономный режим (без сети), проверка «Ваших предложений», подключение браузера одной
кнопкой, телевизоры Xiaomi / Android TV без кодов, несколько телевизоров."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

from src.storage import Store  # noqa: E402


class Temp(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'data')

    def tearDown(self):
        self.temp.cleanup()


class Reply:
    def __init__(self, data, status=200):
        self.data, self.status_code, self.ok = data, status, status < 400

    def json(self):
        return self.data


# ---------------- «Ваши предложения» ----------------
class SupportTests(Temp):
    def server(self, bot, **kw):
        import license_server
        from support import Support as ServerSupport
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        server = license_server.LicenseServer(self.root / 'lic.db', Ed25519PrivateKey.generate(), None)
        support = ServerSupport(server, bot_token='123:abc', session=bot, **kw)
        return license_server.create_app(server, support=support).test_client(), support

    def test_chat_found_automatically_and_check(self):
        bot = Mock()
        updates = {'ok': True, 'result': [
            {'message': {'chat': {'id': -5, 'type': 'group', 'title': 'x'}}},
            {'message': {'chat': {'id': 77, 'type': 'private', 'username': 'someone'}}},
            {'message': {'chat': {'id': 42, 'type': 'private', 'username': 'Orsofey'}}},
            {'message': {'chat': {'id': 99, 'type': 'private', 'username': 'late'}}}]}
        bot.get.side_effect = lambda url, **kw: Reply(updates if 'getUpdates' in url else
                                                       {'ok': True, 'result': {'username': 'andrey_ideas_bot'}})
        bot.post.return_value = Reply({'ok': True})
        web, support = self.server(bot, telegram='orsofey')          # TELEGRAM_CHAT_ID не задан
        check = web.get('/api/support/check').get_json()
        self.assertEqual((check['token'], check['bot_ok'], check['chat'], check['bot_name']),
                         (True, True, True, 'andrey_ideas_bot'))
        self.assertTrue(web.post('/api/support/feedback', json={'text': 'Добавьте кондиционер'}).get_json()['delivered'])
        self.assertEqual(str(bot.post.call_args.kwargs['json']['chat_id']), '42')   # чат владельца по нику
        self.assertNotIn('123:abc', json.dumps(check))                              # токен не раскрывается

    def test_check_explains_telegram_errors(self):
        bot = Mock()
        bot.get.side_effect = lambda url, **kw: Reply({'ok': True, 'result': []} if 'getUpdates' in url else
                                                       {'ok': True, 'result': {'username': 'b'}})
        web, support = self.server(bot)
        check = web.get('/api/support/check').get_json()
        self.assertFalse(check['chat'])
        self.assertIn('/start', check['error'])
        bot.get.side_effect = lambda url, **kw: Reply({'ok': False, 'description': 'Unauthorized'}, 401)
        self.assertIn('Unauthorized', web.get('/api/support/check').get_json()['error'])

    def test_client_check_detects_old_server(self):
        from src.support import Support
        session = Mock()
        session.request.return_value = Reply({}, 404)
        client = Support(self.store, Mock(server_url='https://lic.test', session=session), '6.2')
        result = client.check()
        self.assertFalse(result['ok'])
        self.assertIn('папки server/', result['steps'][-1]['text'])
        self.assertIn('Не задан адрес', Support(self.store, Mock(server_url=''), '6.2').check()['steps'][0]['text'])

    def test_client_check_all_good(self):
        from src.support import Support
        session = Mock()
        session.request.return_value = Reply({'success': True, 'token': True, 'bot_ok': True, 'bot_name': 'b',
                                              'chat': True, 'telegram': 'orsofey'})
        result = Support(self.store, Mock(server_url='https://lic.test', session=session), '6.2').check()
        self.assertTrue(result['ok'], result)


if __name__ == '__main__':
    unittest.main()


# ---------------- автономный режим ----------------
class NetworkTests(Temp):
    def setUp(self):
        super().setUp()
        from src import network
        self.network = network
        self.addCleanup(lambda: network._state.update(online=True))

    def test_local_addresses(self):
        local = self.network.is_local
        for host in ('127.0.0.1', 'localhost', '192.168.1.40', '10.0.0.5', '172.20.1.1', 'tv.local', 'NAS', '::1',
                     'fe80::1', '239.255.255.250', None):
            self.assertTrue(local(host), host)
        for host in ('8.8.8.8', 'api.telegram.org', 'ya.ru', '2a00:1450::1', '172.32.0.1'):
            self.assertFalse(local(host), host)
        self.assertTrue(self.network.is_web_url('https://youtube.com/watch?v=1'))
        self.assertFalse(self.network.is_web_url('http://192.168.1.1/'))

    def test_guard_blocks_internet_but_not_home_network(self):
        import socket
        import webbrowser
        net = self.network.Network(self.store)
        net.set(False)
        with self.assertRaises(socket.gaierror):
            socket.getaddrinfo('example.com', 443)
        sock = socket.socket()
        with self.assertRaises(self.network.Offline):
            sock.connect(('93.184.216.34', 443))
        sock.close()
        self.assertFalse(webbrowser.open('https://ya.ru'))
        self.assertTrue(socket.getaddrinfo('127.0.0.1', 80))        # свой компьютер — можно
        server = socket.socket(); server.bind(('127.0.0.1', 0)); server.listen(1)
        client = socket.socket(); client.connect(server.getsockname())  # локальное соединение работает
        client.close(); server.close()
        net.set(True)
        self.assertTrue(socket.getaddrinfo('127.0.0.1', 80))

    def test_voice_and_persistence(self):
        net = self.network.Network(self.store)
        self.assertIsNone(net.handle('отключи интернет у планшета'))     # это роутер, не агент
        self.assertIn('Отключился от сети', net.handle('Отключись от сети'))
        self.assertFalse(net.online)
        self.assertEqual(self.store.meta('network'), 'off')
        self.assertIn('уже работаю без сети', net.handle('перейди в офлайн режим'))
        self.assertFalse(self.network.Network(self.store).online)      # после перезапуска — тоже без сети
        self.assertIn('без сети', net.handle('ты в сети?'))
        self.assertIn('Подключился', net.handle('Андрей подключись к сети'.split(' ', 1)[1]))
        self.assertTrue(net.online)

    def test_settings_forced_local_and_browser(self):
        net = self.network.Network(self.store)
        net.set(False)
        settings = net.settings({'llm_web_search': True, 'llm_provider': 'openai',
                                 'openai_base_url': 'https://api.groq.com/openai/v1'})
        self.assertEqual((settings['llm_web_search'], settings['llm_provider']), (False, 'local'))
        local = net.settings({'llm_provider': 'openai', 'openai_base_url': 'http://127.0.0.1:11434/v1'})
        self.assertEqual(local['llm_provider'], 'openai')                # Ollama на этом ПК — можно
        browser = Mock()
        wrapped = self.network.OfflineBrowser(browser)
        self.assertIn('без сети', wrapped.call('open', 'https://youtube.com'))
        wrapped.call('tabs')
        browser.call.assert_called_once_with('tabs')

    def test_agent_and_api(self):
        from app import create_app
        from src import connectors
        app = create_app(self.store, Mock(status=Mock(return_value={})), Mock(),
                         license=Mock(is_premium=lambda: True))
        client = app.test_client()
        headers = {'X-Agent-Token': self.store.meta('pairing_token')}
        self.assertTrue(client.get('/api/network', headers=headers).get_json()['online'])
        self.assertFalse(client.post('/api/network', json={'online': False}, headers=headers).get_json()['online'])
        hub = connectors.Connectors(self.store, http=Mock())
        hub.get('todoist').save({'access_token': 't'})
        self.assertIn('без сети', hub.handle('Что в Todoist на сегодня?'))
        client.post('/api/network', json={'online': True}, headers=headers)

    def test_agent_voice_command(self):
        from src.agent import LocalComputerAgent
        agent = LocalComputerAgent(Mock(), brain=None)
        agent.network = self.network.Network(self.store)
        self.assertIn('Отключился', agent.process_command('Андрей, отключись от сети', {'wake_word': 'Андрей'}))
        self.assertIn('Подключился', agent.process_command('Андрей, подключись к сети', {'wake_word': 'Андрей'}))


# ---------------- телевизоры ----------------
class TvParseTests(unittest.TestCase):
    TVS = [{'number': 1, 'name': 'Гостиная'}, {'number': 2, 'name': 'Спальня'}]

    def run_phrase(self, text):
        from src.smarthome import parse_tv
        from src.tv import pick_target
        target, cleaned = pick_target(text, self.TVS)
        return target, parse_tv(cleaned)

    def test_numbered_commands(self):
        self.assertEqual(self.run_phrase('Включи телевизор 1'), (1, ('power', True)))
        self.assertEqual(self.run_phrase('Переключи канал на телевизоре 1'), (1, ('channel_step', 1)))
        self.assertEqual(self.run_phrase('Включи Дюну 1 на телевизоре 2'), (2, ('search', ('дюну 1', 'youtube'))))
        self.assertEqual(self.run_phrase('Включи 5 канал на втором телевизоре'), (2, ('channel', 5)))
        self.assertEqual(self.run_phrase('выключи все телевизоры'), ('all', ('power', False)))
        self.assertEqual(self.run_phrase('на всех телевизорах выключи звук'), ('all', ('mute', True)))
        self.assertEqual(self.run_phrase('телевизор в спальне громче'), (2, ('volume_step', 1)))
        self.assertEqual(self.run_phrase('громкость на телевизоре 20'), (None, ('volume', 20)))   # это громкость
        self.assertEqual(self.run_phrase('нажми ок на телевизоре'), (None, ('key', 'ok')))
        self.assertEqual(self.run_phrase('включи на телевизоре 2 кинопоиск'), (2, ('app', 'kinopoisk')))


class Session:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def _hit(self, method, url, **kw):
        self.calls.append((method, url, kw))
        full = url + '?' + '&'.join(f'{k}={v}' for k, v in (kw.get('params') or {}).items())
        for part, answer in self.routes:
            if part in full:
                return answer
        return Reply({}, 404)

    def get(self, url, **kw):
        return self._hit('GET', url, **kw)

    def post(self, url, **kw):
        return self._hit('POST', url, **kw)


class FakeCast:
    log = []

    def __init__(self, ip):
        self.ip = ip

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def set_volume(self, level):
        FakeCast.log.append(('volume', round(level, 2)))

    def volume(self):
        return 0.5

    def mute(self, muted):
        FakeCast.log.append(('mute', muted))

    def launch(self, app):
        FakeCast.log.append(('launch', app))

    def stop(self):
        FakeCast.log.append(('stop',))

    def status(self):
        return {}


class TvDeviceTests(unittest.TestCase):
    def setUp(self):
        FakeCast.log = []

    def test_xiaomi_without_codes(self):
        from src.tv import XiaomiTV
        apps = Reply({'data': {'AppInfo': [{'PackageName': 'ru.kinopoisk.tv', 'AppName': 'Кинопоиск'},
                                           {'PackageName': 'com.google.android.youtube.tv', 'AppName': 'YouTube'}]}})
        session = Session([('isalive', Reply({'status': 0, 'data': {'devicename': 'Mi TV'}})),
                           ('getinstalledapp', apps), ('/controller', Reply({}))])
        tv = XiaomiTV({'ip': '192.168.1.50'}, session, cast_factory=FakeCast)
        self.assertIn('коды не нужны', tv.pair())
        self.assertEqual(tv.run('power', False), 'Выключаю телевизор.')
        self.assertEqual(session.calls[-1][2]['params'], {'action': 'keyevent', 'keycode': 'power'})
        tv.run('volume_step', 1)
        self.assertEqual([c[2]['params']['keycode'] for c in session.calls[-2:]], ['volumeup', 'volumeup'])
        self.assertEqual(tv.run('volume', 30), 'Громкость телевизора 30.')
        self.assertEqual(FakeCast.log, [('volume', 0.3)])
        self.assertIn('Кинопоиск', tv.run('app', 'kinopoisk'))
        self.assertEqual(session.calls[-1][2]['params']['packagename'], 'ru.kinopoisk.tv')
        tv.run('key', 'ok')
        self.assertEqual(session.calls[-1][2]['params']['keycode'], 'enter')

    def test_android_cast_volume_and_youtube(self):
        from src import tv as tvmod
        session = Session([('/apps/YouTube', Reply({}, 201))])
        device = tvmod.CastTV({'ip': '192.168.1.60'}, session, cast_factory=FakeCast)
        self.assertEqual(device.run('volume', 25), 'Громкость телевизора 25.')
        self.assertEqual(device.run('volume_step', 1), 'Громче.')
        self.assertEqual(FakeCast.log, [('volume', 0.25), ('volume', 0.56)])
        with patch.object(tvmod, 'youtube_video', return_value='abc123'):
            self.assertIn('Дюну', device.run('search', ('Дюну', 'youtube')))
        self.assertEqual(session.calls[-1][2]['data'], 'v=abc123')
        self.assertIn('Отладку по USB', device.run('channel', 5))       # честно: каналы — только с ADB

    def test_cast_protocol_roundtrip(self):
        import struct
        from src.tv import cast_message, parse_cast
        frame = cast_message('sender-0', 'receiver-0', 'urn:x-cast:com.google.cast.receiver', {'type': 'GET_STATUS'})
        length = struct.unpack('>I', frame[:4])[0]
        message = parse_cast(frame[4:4 + length])
        self.assertEqual(message['namespace'], 'urn:x-cast:com.google.cast.receiver')
        self.assertEqual(json.loads(message['payload']), {'type': 'GET_STATUS'})

    def test_mdns_answer_parsed(self):
        import socket
        import struct
        from src.tv import _qname, parse_mdns

        def record(name, rtype, body):
            return _qname(name) + struct.pack('>HHIH', rtype, 0x8001, 120, len(body)) + body
        txt = b''.join(bytes([len(x)]) + x for x in ('fn=Mi TV Гостиная'.encode(), b'md=MiTV-AXFR0'))
        packet = struct.pack('>HHHHHH', 0, 0x8400, 0, 1, 0, 2) + \
            record('_googlecast._tcp.local', 12, _qname('Mi-TV-1._googlecast._tcp.local')) + \
            record('Mi-TV-1._googlecast._tcp.local', 16, txt) + \
            record('mitv.local', 1, socket.inet_aton('192.168.1.50'))
        info = parse_mdns(packet)
        self.assertEqual(info['services'], {'_googlecast._tcp.local'})
        self.assertEqual(info['txt']['fn'], 'Mi TV Гостиная')
        self.assertEqual(info['ips'], ['192.168.1.50'])

    def test_discover_merges_and_classifies(self):
        from src import tv as tvmod
        session = Session([('192.168.1.50:6095', Reply({'status': 0, 'data': {'devicename': 'Mi TV'}})),
                           ('eureka_info', Reply({'name': 'Sony Bravia', 'device_info': {'manufacturer': 'Sony'}}))])
        with patch.object(tvmod, 'local_ipv4s', return_value=['192.168.1.10']), \
                patch.object(tvmod, 'mdns_search', return_value={'192.168.1.60': {'services': {'_googlecast._tcp.local'},
                                                                                 'name': '', 'model': '', 'maker': ''}}), \
                patch.object(tvmod, 'ssdp_search', return_value={}), \
                patch.object(tvmod, 'port_scan', return_value={'192.168.1.50': [6095, 8009], '192.168.1.70': [3001],
                                                               '192.168.1.60': [8009]}), \
                patch.object(tvmod, 'arp_table', return_value={'192.168.1.50': 'AA:BB:CC:DD:EE:01'}):
            found = tvmod.discover(session)
        by_ip = {f['ip']: f for f in found}
        self.assertEqual(by_ip['192.168.1.50']['type'], 'xiaomi')
        self.assertEqual(by_ip['192.168.1.50']['mac'], 'AA:BB:CC:DD:EE:01')
        self.assertEqual((by_ip['192.168.1.60']['type'], by_ip['192.168.1.60']['name']), ('android', 'Sony Bravia'))
        self.assertEqual(by_ip['192.168.1.70']['type'], 'lg')

    def test_arp_parsing_windows(self):
        from src import tv as tvmod
        out = ('Interface: 192.168.1.10 --- 0x5\r\n  Internet Address      Physical Address      Type\r\n'
               '  192.168.1.50          aa-bb-cc-dd-ee-01     dynamic\r\n  192.168.1.255         ff-ff-ff-ff-ff-ff     static\r\n')
        with patch.object(tvmod.sys, 'platform', 'win32'), \
                patch.object(tvmod.subprocess, 'run', return_value=Mock(stdout=out.encode('cp866'))):
            self.assertEqual(tvmod.arp_table(), {'192.168.1.50': 'AA:BB:CC:DD:EE:01'})


class SmartHomeTvTests(Temp):
    def test_old_config_migrates_and_numbers_route(self):
        from src.smarthome import SmartHome
        home = SmartHome(self.store, session=Mock())
        self.store.set_meta('smarthome', json.dumps({'tv': {'type': 'lg', 'ip': '192.168.1.70', 'client_key': 'K'}}))
        self.assertEqual(home.tvs()[0]['number'], 1)
        home.save('tvs', [dict(home.public()['tvs'][0]),
                          {'number': 2, 'name': 'Спальня', 'type': 'xiaomi', 'ip': '192.168.1.50', 'mac': 'AA:BB:CC:DD:EE:01'}])
        saved = json.loads(self.store.meta('smarthome'))
        self.assertNotIn('tv', saved)
        self.assertEqual(saved['tvs'][0]['client_key'], 'K')          # секрет не затёрт «••••••» из формы
        self.assertEqual(home.public()['tvs'][0]['client_key'], '••••••')
        ran = []

        class Device:
            def __init__(self, config):
                self.config = config

            def run(self, action, value):
                ran.append((self.config['number'], action, value))
                return 'ок'

            def pair(self):
                return 'ок'
        with patch.object(SmartHome, 'device', lambda self, config: Device(config)), \
                patch.object(SmartHome, 'detect', lambda self, config: config), \
                patch('src.smarthome.wake_on_lan') as wol:
            self.assertEqual(home.handle('Переключи канал на телевизоре 2'), 'Спальня: ок')
            self.assertEqual(ran[-1], (2, 'channel_step', 1))
            home.handle('включи телевизор 2')
            wol.assert_called_with('AA:BB:CC:DD:EE:01')
            home.handle('выключи все телевизоры')
            self.assertEqual(ran[-2:], [(1, 'power', False), (2, 'power', False)])
            self.assertIn('Телевизора 5 нет', home.handle('включи телевизор номер 5'))
            home.handle('телевизор громче')          # без номера — последний использованный
            self.assertEqual(ran[-1], (2, 'volume_step', 1))


# ---------------- браузер одной кнопкой ----------------
class BrowserSetupTests(Temp):
    def test_prepare_writes_pairing_code(self):
        from src import browser_setup
        folder = browser_setup.prepare(self.root, ROOT, 5000, 'TOKEN123')
        self.assertTrue((folder / 'manifest.json').exists())
        self.assertEqual(json.loads((folder / 'pairing.json').read_text()), {'port': 5000, 'token': 'TOKEN123'})
        background = (ROOT / 'browser_extension' / 'background.js').read_text(encoding='utf-8')
        self.assertIn("getURL('pairing.json')", background)
        self.assertIn('/api/ext/pair-request', background)

    def test_connect_opens_extensions_page(self):
        from src import browser_setup
        with patch.object(browser_setup, 'pick_browser', return_value=('yandex', 'C:/browser.exe')), \
                patch.object(browser_setup, 'launch') as launch, patch.object(browser_setup, 'reveal') as reveal, \
                patch.object(browser_setup, 'store_url', return_value=''):
            result = browser_setup.connect(self.root, ROOT, 5000, 'T')
        launch.assert_called_once_with('yandex', 'C:/browser.exe', 'browser://extensions/')
        reveal.assert_called_once()
        self.assertEqual(result['mode'], 'folder')
        self.assertIn('Режим разработчика', result['steps'][0])
        opened = []
        with patch.object(browser_setup, 'pick_browser', return_value=('chrome', 'chrome.exe')), \
                patch.object(browser_setup, 'store_url', return_value='https://chromewebstore.google.com/detail/x'):
            store = browser_setup.connect(self.root, ROOT, 5000, 'T', opener=opened.append)
        self.assertEqual((store['mode'], opened), ('store', ['https://chromewebstore.google.com/detail/x']))

    def test_pair_request_needs_approval(self):
        import threading
        from app import create_app
        app = create_app(self.store, Mock(status=Mock(return_value={})), Mock(), license=Mock(is_premium=lambda: True))
        client = app.test_client()
        headers = {'X-Agent-Token': self.store.meta('pairing_token')}
        ext = {'Origin': 'chrome-extension://abcdef'}
        self.assertEqual(client.post('/api/ext/pair-request', json={}, headers={'Origin': 'https://evil.example'}).status_code, 403)
        pairs = next(c for c in app.view_functions['ext_pair_answer'].__closure__ or []
                     if hasattr(c.cell_contents, 'ask')).cell_contents
        timer = threading.Timer(0.2, lambda: pairs.answer('Google Chrome', True))
        timer.start()
        data = client.post('/api/ext/pair-request', json={'browser': 'Google Chrome'}, headers=ext).get_json()
        self.assertEqual(data['token'], self.store.meta('pairing_token'))
        pairs.answer('Opera', False)
        threading.Timer(0.2, lambda: pairs.answer('Opera', False)).start()
        self.assertEqual(client.post('/api/ext/pair-request', json={'browser': 'Opera'}, headers=ext).status_code, 403)


class DefaultThemeTests(Temp):
    def test_glass_default_and_one_time_migration(self):
        self.assertEqual(self.store.settings('device:desktop')['theme'], 'glass')
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('device:old', json.dumps({'theme': 'aurora'})))
        self.store.premium = lambda: True
        self.assertEqual(self.store.settings('device:old')['theme'], 'glass')       # прежний «по умолчанию»
        self.store.save_settings('device:old', {'theme': 'aurora'})                  # выбрал «Аврору» сам — остаётся
        self.assertEqual(self.store.settings('device:old')['theme'], 'aurora')


class TvFixesTests(Temp):
    """Ошибки с реальных телевизоров: таймаут Cast, MiTV определялся как Android, непонятное «выключить нельзя»."""

    def test_xiaomi_detected_even_when_found_by_chromecast(self):
        from src import tv as tvmod
        session = Session([('6095/request', Reply({'status': 0, 'data': {'devicename': 'MiTV-MOOQ1'}})),
                           ('eureka_info', Reply({'name': 'MiTV-MOOQ1', 'device_info': {'manufacturer': 'Xiaomi'}}))])
        with patch.object(tvmod, 'port_open', side_effect=lambda ip, port, timeout=0.4: port in (8009, 8008, 6095)):
            found = tvmod.identify('192.168.1.50', session, {'cast': True, 'name': 'MiTV-MOOQ1'})
        self.assertEqual((found['type'], found['os']), ('xiaomi', 'Xiaomi PatchWall (Mi TV)'))
        with patch.object(tvmod, 'port_open', side_effect=lambda ip, port, timeout=0.4: port in (8009, 5555)):
            other = tvmod.identify('192.168.1.60', Session([]), {'cast': True, 'name': 'R3'})
        self.assertEqual((other['type'], other['adb']), ('android', True))

    def test_android_power_off_explains_and_auto_adb(self):
        from src import tv as tvmod
        device = tvmod.CastTV({'ip': '192.168.1.60', 'name': 'R3'}, Session([]), cast_factory=FakeCast,
                              adb_factory=lambda: Mock(run=lambda action, value: 'Выключаю телевизор.'))
        with patch.object(tvmod, 'port_open', return_value=False):
            reply = device.run('power', False)
        self.assertIn('Чтобы выключать «R3» голосом', reply)
        self.assertIn('«Отладку по USB»', reply)
        self.assertNotIn('пульту', reply)
        with patch.object(tvmod, 'port_open', return_value=True):        # отладку включили — ADB подхватится сам
            self.assertEqual(device.run('power', False), 'Выключаю телевизор.')

    def test_timeouts_become_clear_message(self):
        from src.smarthome import SmartHome
        home = SmartHome(self.store, session=Mock())
        home.save_tvs([{'number': 1, 'name': 'MiTV-MOOQ1', 'type': 'android', 'ip': '192.168.1.50', 'detected': True}])

        class Broken:
            def __init__(self, ip):
                pass

            def __enter__(self):
                raise TimeoutError('The read operation timed out')

            def __exit__(self, *a):
                pass
        from src import tv as tvmod
        with patch.object(tvmod, 'Cast', Broken), patch.object(tvmod, 'port_open', return_value=False):
            reply = home.handle('громкость на телевизоре 20')
        self.assertNotIn('read operation', reply)
        self.assertIn('не отвечает', reply)

    def test_cast_connect_sends_sender_info(self):
        import struct
        from src.tv import Cast, parse_cast
        sent = []

        class Sock:
            def sendall(self, data):
                sent.append(parse_cast(data[4:4 + struct.unpack('>I', data[:4])[0]]))

            def close(self):
                pass
        with Cast('1.2.3.4', connector=lambda ip, port: Sock()):
            pass
        first = json.loads(sent[0]['payload'])
        self.assertEqual(first['type'], 'CONNECT')
        self.assertIn('senderInfo', first)

    def test_old_tv_redetected_once(self):
        from src.smarthome import SmartHome
        from src import tv as tvmod
        home = SmartHome(self.store, session=Mock())
        home.save_tvs([{'number': 1, 'name': 'MiTV', 'type': 'android', 'ip': '192.168.1.50'}])
        found = {'type': 'xiaomi', 'os': 'Xiaomi PatchWall (Mi TV)', 'adb': False, 'cast': True}
        with patch.object(tvmod, 'identify', return_value=found), patch.object(tvmod, 'arp_table', return_value={}), \
                patch.object(tvmod.XiaomiTV, 'key', lambda self, code, times=1: None):
            self.assertEqual(home.handle('выключи телевизор'), 'Выключаю телевизор.')
        saved = home.tvs()[0]
        self.assertEqual((saved['type'], saved['detected']), ('xiaomi', True))


# ---------------- пульт Android TV без отладки ----------------
def _cert(cn):
    import datetime
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.DER)


class FakeTvChannel:
    """Телевизор по ту сторону: отвечает «200 OK» и записывает, что ему прислали."""
    sent = []

    def __init__(self, server_der, script=None):
        self.server_der = server_der
        self.script = list(script or [])

    def __call__(self, ip, port, root):
        FakeTvChannel.sent = []
        return self

    def peer_der(self):
        return self.server_der

    def send(self, payload):
        from src.atv_remote import decode
        FakeTvChannel.sent.append(decode(payload))

    def recv(self):
        from src.atv_remote import decode, f_int
        if self.script:
            return decode(self.script.pop(0))
        return decode(f_int(1, 2) + f_int(2, 200))

    def close(self):
        pass


class AtvRemoteTests(Temp):
    def test_protobuf_and_spoken_code(self):
        from src.atv_remote import decode, f_bytes, f_int, f_msg, first, parse_code
        data = f_int(1, 2) + f_int(2, 200) + f_msg(10, f_bytes(1, 'atvremote'))
        fields = decode(data)
        self.assertEqual((first(fields, 1), first(fields, 2)), (2, 200))
        self.assertEqual(first(decode(first(fields, 10)), 1), b'atvremote')
        self.assertEqual(parse_code('код 4F7A2C'), '4F7A2C')
        self.assertEqual(parse_code('Код 4f 7a 2c'), '4F7A2C')
        self.assertEqual(parse_code('код четыре эф семь а два цэ'), '4F7A2C')
        self.assertEqual(parse_code('пин-код: 1 2 3 4 5 6'), '123456')
        self.assertIsNone(parse_code('код да винчи'))
        self.assertIsNone(parse_code('включи телевизор'))

    def test_pairing_secret_and_wrong_code(self):
        import hashlib
        from src import atv_remote
        client, server = _cert('pc'), _cert('tv')
        # код, который показал бы телевизор: первый байт — контрольный байт секрета
        from cryptography import x509
        nums = [x509.load_der_x509_certificate(c).public_key().public_numbers() for c in (client, server)]
        digest = hashlib.sha256()
        for part in (nums[0].n, nums[0].e, nums[1].n, nums[1].e):
            digest.update(atv_remote._hex_bytes(part))
        digest.update(bytes.fromhex('7A2C'))
        code = f'{digest.digest()[0]:02X}7A2C'
        self.assertEqual(atv_remote.pairing_secret(client, server, code), digest.digest())
        wrong = f'{(digest.digest()[0] + 1) % 256:02X}7A2C'
        with self.assertRaises(atv_remote.RemoteError):
            atv_remote.pairing_secret(client, server, wrong)

    def test_pairing_conversation(self):
        from src import atv_remote
        fake = FakeTvChannel(_cert('tv'))
        session = atv_remote.Pairing('192.168.1.60', self.root, channel_factory=fake)
        session.start()
        self.assertEqual([sorted(k for k in m if k >= 10) for m in FakeTvChannel.sent], [[10], [20], [30]])
        with patch.object(atv_remote, 'pairing_secret', return_value=b'S' * 32):
            self.assertTrue(session.finish('4f7a2c'))
        self.assertEqual(atv_remote.first(atv_remote.decode(atv_remote.first(FakeTvChannel.sent[-1], 40)), 1), b'S' * 32)
        self.assertTrue((self.root / 'tv' / 'atv_client.pem').exists())   # сертификат этого ПК создан один раз

    def test_remote_handshake_and_power(self):
        from src import atv_remote
        from src.atv_remote import f_int, f_msg
        script = [f_msg(1, f_int(1, 1)), f_msg(2, f_int(1, 1)), f_msg(40, f_int(1, 1))]   # configure, active, экран вкл
        fake = FakeTvChannel(b'', script)
        with atv_remote.Remote('192.168.1.60', self.root, channel_factory=fake) as remote:
            self.assertTrue(remote.screen_on)
            self.assertTrue(remote.power(False))
            remote.link('https://www.youtube.com/watch?v=abc')
        kinds = [sorted(m) for m in FakeTvChannel.sent]
        self.assertEqual(kinds[:2], [[1], [2]])                        # ответили на configure и set_active
        key = atv_remote.decode(atv_remote.first(FakeTvChannel.sent[2], 10))
        self.assertEqual((atv_remote.first(key, 1), atv_remote.first(key, 2)), (26, 3))   # POWER, короткое нажатие
        self.assertEqual(atv_remote.first(atv_remote.decode(atv_remote.first(FakeTvChannel.sent[3], 90)), 1),
                         b'https://www.youtube.com/watch?v=abc')

    def test_voice_flow_code_then_command_runs(self):
        from src import atv_remote, tv as tvmod
        from src.smarthome import SmartHome
        home = SmartHome(self.store, session=Mock())
        home.save_tvs([{'number': 2, 'name': 'R3', 'type': 'android', 'ip': '192.168.1.60', 'detected': True,
                        'remote': True}])
        pressed = []

        class FakeRemote:
            screen_on = True

            def __init__(self, ip, root):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def power(self, on):
                pressed.append(('power', on))
                return True

            def key(self, name, times=1):
                pressed.append((name, times))

            def link(self, url):
                pressed.append(('link', url))
        finished = []
        with patch.object(atv_remote, 'Remote', FakeRemote), \
                patch.object(atv_remote.Pairing, 'start', lambda self: None), \
                patch.object(atv_remote.Pairing, 'finish', lambda self, code: finished.append(code) or True), \
                patch.object(tvmod, 'port_open', return_value=False):
            reply = home.handle('выключи телевизор 2')
            self.assertIn('Скажите: «Андрей, код', reply)
            self.assertNotIn('Отладку', reply)
            self.assertTrue(home.awaiting('device:desktop'))
            reply = home.handle('код четыре эф семь а два цэ')
            self.assertEqual(finished, ['4F7A2C'])
            self.assertIn('подключён', reply)
            self.assertIn('Выключаю телевизор', reply)                 # отложенная команда выполнилась сама
            self.assertEqual(pressed, [('power', False)])
            self.assertTrue(home.tvs()[0]['paired'])
            self.assertEqual(home.handle('переключи канал на телевизоре 2'), 'R3: Следующий канал.' if len(home.tvs()) > 1
                             else 'Следующий канал.')
            self.assertEqual(pressed[-1], ('channel_up', 1))
            home.handle('включи на телевизоре 5 канал')
            self.assertEqual(pressed[-1], ('5', 1))

    def test_api_tvcode_without_pairing(self):
        from app import create_app
        app = create_app(self.store, Mock(status=Mock(return_value={})), Mock(),
                         license=Mock(is_premium=lambda: True))
        client = app.test_client()
        headers = {'X-Agent-Token': self.store.meta('pairing_token')}
        result = client.post('/api/smarthome/tvcode', json={'code': '4F7A2C'}, headers=headers).get_json()
        self.assertTrue(result['success'])
        self.assertIn('новый код', result['message'])
        self.assertIsNone(result['waiting_code'])
