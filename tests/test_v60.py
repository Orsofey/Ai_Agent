"""6.0: поддержка, документы в чате, мгновенный поиск, вопросы по документам, порядок в файлах, зрение, игры,
голоса, заказы, умный дом."""
import io
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import date
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


# ---------------- поддержка ----------------
class SupportTests(Temp):
    def test_server_forwards_to_telegram_and_client_sends(self):
        import license_server
        from support import Support as ServerSupport
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        server = license_server.LicenseServer(self.root / 'lic.db', Ed25519PrivateKey.generate(), None)
        bot = Mock()
        bot.post.return_value = Mock(ok=True, json=lambda: {'ok': True})
        support = ServerSupport(server, telegram='@orsofey_dev', bot_token='123:abc', chat_id='42', session=bot)
        app = license_server.create_app(server, support=support)
        web = app.test_client()
        self.assertEqual(web.get('/api/support').get_json()['link'], 'https://t.me/orsofey_dev')
        data = web.post('/api/support/feedback', json={'text': 'Добавьте кондиционер', 'contact': '@me'}).get_json()
        self.assertTrue(data['delivered'])
        sent = bot.post.call_args.kwargs['json']
        self.assertEqual(sent['chat_id'], '42')
        self.assertIn('Добавьте кондиционер', sent['text'])
        self.assertEqual(web.post('/api/support/feedback', json={'text': 'a'}).status_code, 400)
        self.assertEqual(web.get('/support/list?key=x').status_code, 403)

        from src.support import Support, parse
        from tests.test_subscription import ServerSession
        license = Mock(server_url='https://lic.test', session=ServerSession(web))
        opened = []
        client = Support(self.store, license, '6.0', opener=opened.append)
        self.assertEqual(client.info()['telegram'], 'orsofey_dev')
        self.assertIn('Telegram', client.handle('предложение: добавьте будильник'))
        self.assertEqual(parse('хочу предложить сделать тёмную тему')[0], 'send')
        self.assertEqual(parse('напиши разработчику лично'), ('open',))
        self.assertIsNone(parse('напиши Милане в телеграм привет'))
        client.open_telegram('')
        self.assertEqual(opened, ['https://t.me/orsofey_dev'])

    def test_offline_queue(self):
        from src.support import Support
        client = Support(self.store, Mock(server_url=''), '6.0')
        result = client.send('Сделайте виджет погоды')
        self.assertTrue(result['queued'])
        self.assertTrue((self.store.root / 'feedback_outbox.jsonl').exists())


# ---------------- документы в чате ----------------
class DocumentsTests(Temp):
    def test_publish_adds_attachment_to_history_and_event(self):
        from src.documents import Documents, parse
        events = Mock()
        docs = Documents(self.store, events)
        path = self.root / 'справка.md'
        path.write_text('текст', encoding='utf-8')
        card = docs.publish(path, 'Готово')
        history = self.store.history('device:desktop')
        self.assertEqual(history[-1]['attachment']['name'], 'справка.md')
        self.assertEqual(events.emit.call_args.kwargs['attachment']['id'], card['id'])
        self.assertEqual(docs.get(card['id']), path.resolve())
        self.assertEqual(parse('Отправь этот файл Милане в Телеграм'),
                         {'action': 'messenger', 'app': 'telegram', 'who': 'Милане', 'what': 'этот файл'})
        self.assertEqual(parse('отправь справку на почту ivan@mail.ru')['to'], 'ivan@mail.ru')
        self.assertEqual(parse('сохрани его на рабочий стол')['folder'], 'рабочий стол')
        self.assertIsNone(parse('напиши Милане в телеграм привет'))

    def test_save_to_folder_uses_last_document(self):
        from src.documents import Documents
        docs = Documents(self.store)
        path = self.root / 'отчёт.pdf'
        path.write_bytes(b'%PDF')
        docs.publish(path)
        target = self.root / 'Стол'
        target.mkdir()
        with patch('src.documents.oshelp.selected_files', return_value=[]), \
                patch('src.files.resolve_folder', return_value=target):
            reply = docs.handle('сохрани его на рабочий стол')
        self.assertIn('Сохранил', reply)
        self.assertTrue((target / 'отчёт.pdf').exists())


# ---------------- мгновенный поиск и вопросы по документам ----------------
class IndexTests(Temp):
    def make_files(self):
        folder = self.root / 'Документы'
        folder.mkdir()
        (folder / 'Договор аренды.txt').write_text('Срок аренды — 11 месяцев. Оплата до 10 числа каждого месяца.\n'
                                                   'Арендатор обязан поддерживать порядок.', encoding='utf-8')
        (folder / 'Годовойотчет2025.txt').write_text('Выручка выросла', encoding='utf-8')
        (folder / 'рецепт.txt').write_text('Борщ: свёкла, капуста', encoding='utf-8')
        return folder

    def test_search_names_text_and_substring(self):
        from src.file_index import FileIndex, FileSearch
        folder = self.make_files()
        index = FileIndex(self.root / 'data', folders=lambda: [folder])
        index.scan()
        self.assertEqual(index.status()['files'], 3)
        self.assertEqual(index.search('договор')[0]['name'], 'Договор аренды.txt')
        self.assertEqual(index.search('свёкла')[0]['name'], 'рецепт.txt')      # по тексту
        self.assertEqual(index.search('отчет')[0]['name'], 'Годовойотчет2025.txt')  # подстрока в имени
        self.assertLess(index.last_elapsed, 500)
        (folder / 'рецепт.txt').unlink()
        index.scan()
        self.assertEqual(index.status()['files'], 2)
        opened = []
        search = FileSearch(index, opener=opened.append)
        self.assertIn('Нашёл', search.handle('найди документы про аренду', 'o'))
        self.assertIn('Открываю', search.handle('открой первый', 'o'))
        self.assertEqual(opened[0].name, 'Договор аренды.txt')

    def test_document_question(self):
        from src.doc_qa import DocumentQA, best_chunks, parse
        from src.file_index import FileIndex
        folder = self.make_files()
        index = FileIndex(self.root / 'data', folders=lambda: [folder])
        index.scan()
        request = parse('Что в договоре сказано про сроки?')
        self.assertEqual(request['noun'], 'договоре')
        self.assertIsNone(parse('найди в файлах слово договор'))
        self.assertIsNone(parse('какая погода завтра'))
        brain = Mock()
        brain.complete.return_value = 'Срок аренды — 11 месяцев.'
        qa = DocumentQA(index, brain=brain)
        answer = qa.handle('Что в договоре сказано про сроки?')
        self.assertIn('Договор аренды.txt', answer)
        self.assertIn('11 месяцев', brain.complete.call_args.args[1])
        self.assertTrue(best_chunks('a ' * 3000 + ' срок оплаты', 'какой срок оплаты'))


# ---------------- порядок в файлах ----------------
class FileOpsTests(Temp):
    def setUp(self):
        super().setUp()
        self.downloads = self.root / 'Downloads'
        self.downloads.mkdir()
        old = time.time() - 3600
        for name in ('счёт.pdf', 'фото.jpg', 'архив.zip', 'setup.exe', 'заметка.xyz', 'scan0001.pdf', 'IMG_2031.jpg'):
            path = self.downloads / name
            path.write_bytes(name.encode() * 300)
            os.utime(path, (old, old))

    def ops(self):
        from src.file_ops import FileOps
        return FileOps(self.store, documents=Mock())

    def test_tidy_confirm_and_undo(self):
        ops = self.ops()
        with patch('src.files.resolve_folder', return_value=self.downloads):
            question = ops.handle('наведи порядок в загрузках', 'o')
        self.assertIn('Документы', question)
        self.assertTrue(ops.awaiting('o'))
        self.assertTrue((self.downloads / 'счёт.pdf').exists())      # без «да» ничего не меняется
        self.assertIn('Разложил', ops.handle('да', 'o'))
        self.assertTrue((self.downloads / 'Документы' / 'счёт.pdf').exists())
        self.assertTrue((self.downloads / 'Картинки' / 'фото.jpg').exists())
        self.assertTrue((self.downloads / 'Архивы' / 'архив.zip').exists())
        self.assertTrue((self.downloads / 'заметка.xyz').exists())    # неизвестное — на месте
        self.assertIn('Вернул', ops.handle('отмени', 'o') or ops.handle('верни как было', 'o'))
        self.assertTrue((self.downloads / 'счёт.pdf').exists())
        self.assertFalse((self.downloads / 'Документы').exists())

    def test_no_means_nothing(self):
        ops = self.ops()
        with patch('src.files.resolve_folder', return_value=self.downloads):
            ops.handle('наведи порядок в загрузках', 'o')
        self.assertIn('ничего не меняю', ops.handle('нет', 'o'))
        self.assertTrue((self.downloads / 'счёт.pdf').exists())

    def test_rename_scans_by_date(self):
        from src.file_ops import plan_rename
        moves = plan_rename(self.downloads)
        names = {a.name: b.name for a, b in moves}
        self.assertIn('scan0001.pdf', names)
        self.assertTrue(names['scan0001.pdf'].startswith('Скан '))
        self.assertTrue(names['IMG_2031.jpg'].startswith('Фото '))
        self.assertNotIn('счёт.pdf', names)

    def test_duplicates(self):
        from src.file_ops import find_duplicates
        (self.downloads / 'копия.pdf').write_bytes((self.downloads / 'счёт.pdf').read_bytes())
        groups = find_duplicates([self.downloads])
        self.assertEqual(len(groups), 1)
        self.assertEqual({p.name for p in groups[0]}, {'счёт.pdf', 'копия.pdf'})
        ops = self.ops()
        with patch('src.files.resolve_folder', return_value=self.downloads), \
                patch('src.file_ops.output_folder', return_value=self.root):
            reply = ops.handle('найди дубликаты в загрузках', 'o')
        self.assertIn('копий', reply)
        with patch('src.file_ops.oshelp.to_trash', side_effect=lambda paths: list(paths)) as trash:
            self.assertIn('Корзину', ops.handle('да', 'o'))
        self.assertEqual(len(trash.call_args.args[0]), 1)

    def test_make_pdf_from_images_and_text(self):
        from PIL import Image
        from pypdf import PdfReader
        from src.file_ops import make_pdf, parse
        image = self.root / 'a.png'
        Image.new('RGB', (200, 100), 'red').save(image)
        text = self.root / 'b.txt'
        text.write_text('Привет, мир\n' * 5, encoding='utf-8')
        target, skipped = make_pdf([image, text, self.downloads / 'setup.exe'], self.root / 'out.pdf')
        self.assertEqual(len(PdfReader(str(target)).pages), 2)
        self.assertEqual([p.name for p in skipped], ['setup.exe'])
        self.assertEqual(parse('сделай из этих файлов pdf'), ('pdf',))


# ---------------- зрение ----------------
class VisionTests(Temp):
    def test_parse(self):
        from src.vision import parse, pick_files
        self.assertEqual(parse('Что это?')[0], 'cursor')
        self.assertEqual(parse('что здесь написано')[0], 'cursor')
        self.assertEqual(parse('сейчас обведу')[0], 'area')
        self.assertEqual(parse('что на экране')[0], 'screen')
        self.assertIsNone(parse('что это за песня играет в клипе'))
        model, projector = pick_files(['Qwen3VL-2B-Instruct-Q4_K_M.gguf', 'Qwen3VL-2B-Instruct-Q8_0.gguf',
                                       'mmproj-Qwen3VL-2B-Instruct-F16.gguf', 'README.md'])
        self.assertEqual((model, projector), ('Qwen3VL-2B-Instruct-Q4_K_M.gguf', 'mmproj-Qwen3VL-2B-Instruct-F16.gguf'))

    def test_model_then_ocr_fallback(self):
        from PIL import Image
        from src.vision import Vision
        image = Image.new('RGB', (100, 60), 'white')
        server = Mock()
        server.installed.return_value = True
        server.describe.return_value = 'Это кнопка «Сохранить».'
        vision = Vision(self.root, server=server, grabber={'cursor': lambda: image}, ocr=lambda img: '')
        self.assertEqual(vision.handle('что это'), 'Это кнопка «Сохранить».')
        server.installed.return_value = False
        vision.ocr = lambda img: 'Итого: 1500 ₽'
        self.assertIn('Итого: 1500', vision.handle('что это'))


# ---------------- игры ----------------
class GamesTests(Temp):
    def test_mode_and_keys(self):
        from src.games import Games, parse_keys
        keys = Mock()
        games = Games(self.store, keys=keys, process=lambda: 'javaw.exe')
        self.assertFalse(games.run_phrase('прыжок'))                 # режим выключен
        self.assertIn('Minecraft', games.handle('включи игровой режим'))
        self.assertTrue(games.run_phrase('прыжок'))
        time.sleep(0.2)
        keys.down.assert_any_call('space')
        self.assertFalse(games.run_phrase('привет как дела'))         # разговор игнорируется
        self.assertEqual(parse_keys('hold shift+w 2'), {'kind': 'hold', 'keys': ['shift', 'w'], 'seconds': 2.0})
        self.assertEqual(parse_keys('click right')['button'], 'right')
        self.assertIn('выключен', games.handle('выключи игровой режим'))

    def test_custom_profile_saved(self):
        from src.games import Games
        games = Games(self.store, keys=Mock(), process=lambda: '')
        games.save_profiles({'Моя игра': 'щит = q'})
        games.handle('включи игровой режим для моя игра')
        self.assertEqual(games.current_profile(), 'Моя игра')
        self.assertEqual(games.match('щит')['keys'], ['q'])


# ---------------- голоса ----------------
class VoiceCatalogTests(Temp):
    CATALOG = {'ru_RU-irina-medium': {'name': 'irina', 'quality': 'medium', 'num_speakers': 1,
                                      'language': {'family': 'ru', 'code': 'ru_RU', 'name_native': 'Русский'},
                                      'files': {'ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx': {'size_bytes': 63 * 2 ** 20},
                                                'ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json': {'size_bytes': 5000},
                                                'ru/ru_RU/irina/medium/MODEL_CARD': {'size_bytes': 300}}},
               'en_US-amy-low': {'name': 'amy', 'quality': 'low', 'language': {'family': 'en', 'code': 'en_US'}, 'files': {}}}

    def test_list_and_install(self):
        from src import voice_catalog
        self.assertEqual(list(voice_catalog.languages(self.CATALOG))[:2], ['ru', 'en'])
        voices = voice_catalog.list_voices(self.CATALOG, 'ru', self.store.root)
        self.assertEqual(voices[0]['size_mb'], 63)

        def fake(url, destination, session=None, progress=None):
            Path(destination).parent.mkdir(parents=True, exist_ok=True)
            Path(destination).write_text('{"audio": {}}' if str(destination).endswith('.json') else 'x', encoding='utf-8')
        with patch('src.model_downloader.http_download', side_effect=fake):
            voice = voice_catalog.install(self.store.root, 'ru_RU-irina-medium', self.CATALOG)
        self.assertEqual(voice['id'], 'custom:ru_RU-irina-medium')
        from src.local_tts_service import custom_voices
        self.assertIn('Irina', custom_voices(self.store.root)[0]['title'])
        with self.assertRaises(ValueError):
            voice_catalog.install(self.store.root, '../evil', self.CATALOG)


# ---------------- заказы ----------------
class BookingTests(unittest.TestCase):
    def test_parse_and_urls(self):
        from src.booking import Booking, aviasales_url, parse, parse_date, parse_flight
        today = date(2026, 9, 30)
        self.assertEqual(parse_date('на 5 октября', today), date(2026, 10, 5))
        self.assertEqual(parse_date('завтра', today), date(2026, 10, 1))
        self.assertEqual(parse_date('на 3 марта', today), date(2027, 3, 3))
        flight = parse_flight('из Москвы в Сочи на 5 октября и обратно 12 октября на двоих', today=today)
        self.assertEqual(aviasales_url(flight), 'https://www.aviasales.ru/search/MOW0510AER12102')
        self.assertEqual(parse('закажи пиццу')[0], 'food')
        self.assertIsNone(parse('закажи такси'))
        self.assertEqual(parse('забронируй столик в Пушкине на 19:00 на троих')[0], 'table')
        opened = []
        booking = Booking(opened.append)
        self.assertIn('Яндекс Еда', booking.handle('закажи суши'))
        self.assertIn('eda.yandex.ru/search?query=', opened[-1])
        self.assertIn('Авиасейлс', booking.handle('купи билет на самолёт в Казань на завтра'))
        self.assertIn('aviasales.ru/search/MOW', opened[-1])
        self.assertIn('Пушкин', booking.handle('забронируй столик в Пушкине на 19:00 на троих'))
        self.assertIn('yandex.ru/maps', opened[-1])


# ---------------- умный дом ----------------
class SmartHomeTests(Temp):
    def test_parsers(self):
        from src.smarthome import parse_lights, parse_router, parse_tv
        self.assertEqual(parse_tv('громкость телевизора 20'), ('volume', 20))
        self.assertEqual(parse_tv('переключи на 5 канал'), ('channel', 5))
        self.assertEqual(parse_tv('открой на телевизоре кинопоиск'), ('app', 'kinopoisk'))
        self.assertEqual(parse_tv('включи на телевизоре интерстеллар на ютубе'), ('search', ('интерстеллар', 'youtube')))
        self.assertIsNone(parse_tv('сделай погромче'))
        self.assertEqual(parse_lights('включи свет в спальне'), ('on', 'спальне'))
        self.assertEqual(parse_lights('яркость света в спальне 40 процентов'), ('brightness', (40, 'спальне')))
        self.assertIsNone(parse_lights('позвони светлане синицыной'))
        self.assertEqual(parse_router('перезагрузи роутер'), ('reboot', None))

    def test_lights_and_router_confirmation(self):
        from src.smarthome import SmartHome
        home = SmartHome(self.store)
        provider = Mock()
        provider.devices.return_value = [
            {'id': 'l1', 'name': 'Люстра', 'room': 'Спальня', 'type': 'devices.types.light', 'provider': 'x'},
            {'id': 'l2', 'name': 'Лампа', 'room': 'Кухня', 'type': 'devices.types.light', 'provider': 'x'}]
        home.save('lights', {'yandex_token': 'secret'})
        self.assertEqual(home.public()['lights']['yandex_token'], '••••••')
        home.save('lights', {'yandex_token': '••••••'})                   # «не менять» из формы
        self.assertEqual(home.config()['lights']['yandex_token'], 'secret')
        with patch.object(SmartHome, 'light_providers', return_value=[provider]):
            self.assertIn('спальне', home.handle('включи свет в спальне', 'o'))
        provider.act.assert_called_with(['l1'], 'on', None)
        router = Mock()
        home.save('router', {'type': 'keenetic', 'address': '192.168.1.1', 'password': 'p'})
        with patch.object(SmartHome, 'router', return_value=router):
            self.assertIn('Скажите «да»', home.handle('перезагрузи роутер', 'o'))
            router.reboot.assert_not_called()
            self.assertIn('Перезагружаю', home.handle('да', 'o'))
        router.reboot.assert_called_once()

    def test_tv_power_on_uses_wake_on_lan(self):
        from src.smarthome import SmartHome
        home = SmartHome(self.store)
        home.save('tv', {'type': 'lg', 'ip': '192.168.1.40', 'mac': 'AA:BB:CC:DD:EE:FF'})
        with patch('src.smarthome.wake_on_lan') as wol:
            self.assertIn('Включаю', home.handle('включи телевизор', 'o'))
        wol.assert_called_once_with('AA:BB:CC:DD:EE:FF')
        with patch('src.smarthome.LGTV.request', return_value={}) as request:
            self.assertIn('Громкость', home.handle('громкость телевизора 15', 'o'))
        request.assert_called_with('ssap://audio/setVolume', {'volume': 15})

    def test_keenetic_auth_hash(self):
        from src.smarthome import Keenetic
        session = Mock()
        session.get.return_value = Mock(status_code=401, headers={'X-NDM-Realm': 'R', 'X-NDM-Challenge': 'C'})
        session.post.return_value = Mock(status_code=200)
        Keenetic({'address': '192.168.1.1', 'login': 'admin', 'password': 'pw'}, session).auth()
        import hashlib
        md5 = hashlib.md5(b'admin:R:pw').hexdigest()
        self.assertEqual(session.post.call_args.kwargs['json']['password'], hashlib.sha256(('C' + md5).encode()).hexdigest())


# ---------------- агент и API ----------------
class AgentApiTests(Temp):
    def test_routes_and_endpoints(self):
        from app import create_app
        from src.agent import LocalComputerAgent
        agent = LocalComputerAgent(Mock(), brain=None)
        speech = Mock()
        speech.status.return_value = {'ready': True}
        app = create_app(self.store, speech, agent, license=Mock(is_premium=lambda: True, server_url='', session=Mock()))
        web = app.test_client()
        headers = {'X-Agent-Token': self.store.meta('pairing_token'), 'X-Device-ID': 'desktop'}
        for name in ('documents', 'file_search', 'doc_qa', 'file_ops', 'vision', 'games', 'booking', 'smarthome', 'support'):
            self.assertIsNotNone(getattr(agent, name), name)
        with patch('src.web_services.system_open', return_value=True):
            self.assertIn('Яндекс Еда', agent.process_command('Андрей, закажи пиццу', {}))
        self.assertIn('Игровой режим включён', agent.process_command('включи игровой режим', {}))
        agent.games.active = False
        self.assertTrue(web.get('/api/files/status', headers=headers).get_json()['success'])
        self.assertEqual(web.get('/api/files/search?q=abc', headers=headers).status_code, 200)
        data = web.post('/api/smarthome/save', json={'section': 'router', 'data': {'password': 'x', 'type': 'keenetic'}},
                        headers=headers).get_json()
        self.assertEqual(data['config']['router']['password'], '••••••')
        self.assertEqual(web.post('/api/support/feedback', json={'text': 'идея'}, headers=headers).get_json()['queued'], True)
        self.assertIn('profiles', web.get('/api/games', headers=headers).get_json())
        self.assertEqual(web.post('/api/files/open', json={'path': '/etc/passwd'}, headers=headers).status_code, 400)
        page = web.get('/').text
        self.assertIn('Ваши предложения', page)
        self.assertIn('file-search', page)
        settings = web.get('/settings').text
        for page_id in ('page-files', 'page-games', 'page-smarthome', 'vc-load', 'vision-download'):
            self.assertIn(page_id, settings)


if __name__ == '__main__':
    unittest.main()
