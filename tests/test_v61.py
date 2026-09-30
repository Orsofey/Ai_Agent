"""6.1: коннекторы — календари, почта, задачи, облака, Т-Инвестиции, CRM, Spotify, Microsoft 365, GitLab/Jira/Linear;
Home Assistant — кондиционеры, датчики, пылесосы, камеры."""
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from src import connectors, connectors_apps as apps
from src.smarthome import SmartHome, parse_home


def blank_keys(case):
    """Тесты не должны зависеть от ключей, которые разработчик вписал в connector_config.py или переменные окружения."""
    from src import connectors_apps
    for name in dir(connectors.cfg):
        if name.isupper():
            patcher = patch.object(connectors.cfg, name, '')
            patcher.start()
            case.addCleanup(patcher.stop)
    classes = [v for m in (connectors, connectors_apps) for v in vars(m).values()
               if isinstance(v, type) and issubclass(v, connectors.OAuthConnector) and v is not connectors.TrackerConnector]
    for cls in classes:
        for attr in ('client_id', 'client_secret'):
            if attr in vars(cls):
                patcher = patch.object(cls, attr, '')
                patcher.start()
                case.addCleanup(patcher.stop)


class Store:
    def __init__(self, root='.'):
        self.data = {}
        self.root = root

    def meta(self, key):
        return self.data.get(key)

    def set_meta(self, key, value):
        if value is None:
            self.data.pop(key, None)
        else:
            self.data[key] = value


class Isolated(unittest.TestCase):
    def setUp(self):
        blank_keys(self)


class Response:
    def __init__(self, payload=None, status=200, url='', content=None):
        self.payload = payload
        self.status_code = status
        self.url = url
        self.content = content if content is not None else json.dumps(payload or {}).encode()
        self.text = self.content.decode('utf-8', 'ignore') if isinstance(self.content, bytes) else str(self.content)

    def json(self):
        if self.payload is None:
            raise ValueError('no json')
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class Http:
    """Ответы по (метод, кусок адреса); все запросы записываются в calls."""

    def __init__(self, routes=()):
        self.routes = list(routes)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for want, part, answer in self.routes:
            if want == method and part in url:
                result = answer(url, kwargs) if callable(answer) else answer
                if isinstance(result, Response):
                    result.url = result.url or url
                    return result
                return Response(result, url=url)
        return Response({}, url=url)

    def get(self, url, **kwargs):
        return self.request('GET', url, **kwargs)

    def post(self, url, **kwargs):
        return self.request('POST', url, **kwargs)

    def put(self, url, **kwargs):
        return self.request('PUT', url, **kwargs)


def hub_with(routes=(), documents=None):
    store = Store()
    opened = []
    hub = connectors.Connectors(store, http=Http(routes), opener=opened.append, documents=documents)
    hub.opened = opened
    return hub


def connect(hub, connector_id, **saved):
    connector = hub.get(connector_id)
    connector.save(dict({'access_token': 'tok', 'user': 'me'}, **saved))
    return connector


MOMENT = datetime(2026, 9, 30, 10, 0).astimezone()


class WhenTests(Isolated):
    def test_split_when(self):
        parts = apps.split_when('с Иваном завтра в 15:00 на полчаса', MOMENT)
        self.assertEqual(parts['day'], date(2026, 10, 1))
        self.assertEqual(parts['time'], (15, 0))
        self.assertEqual(parts['minutes'], 30)
        self.assertEqual(parts['rest'], 'с Иваном')

    def test_split_when_words_and_afternoon(self):
        parts = apps.split_when('обсуждение проекта в три часа дня 5 октября', MOMENT)
        self.assertEqual(parts['day'], date(2026, 10, 5))
        self.assertEqual(parts['time'], (15, 0))
        self.assertEqual(parts['rest'], 'обсуждение проекта')
        self.assertEqual(apps.split_when('в 3', MOMENT)['time'], (15, 0))    # встреча «в 3» — днём

    def test_period(self):
        start, end, label = apps.period('что у меня завтра', MOMENT)
        self.assertEqual((start.date(), end.date(), label), (date(2026, 10, 1), date(2026, 10, 2), 'завтра'))
        start, end, label = apps.period('на этой неделе', MOMENT)
        self.assertEqual(label, 'на этой неделе')
        self.assertEqual(end.date(), date(2026, 10, 5))


class CalendarTests(Isolated):
    def test_google_calendar_list_and_create(self):
        today = apps.now().date()
        events = {'items': [{'summary': 'Планёрка', 'start': {'dateTime': f'{today}T10:00:00+03:00'}},
                            {'summary': 'День рождения', 'start': {'date': str(today)}}]}
        hub = hub_with([('GET', 'calendar/v3', events), ('POST', 'calendar/v3', {'id': 'e1'})])
        connect(hub, 'google_calendar', scope='openid email https://www.googleapis.com/auth/calendar.events')
        reply = hub.handle('Что у меня сегодня в календаре?')
        self.assertIn('2 события', reply)
        self.assertIn('весь день — День рождения', reply)
        self.assertIn('Планёрка', reply)
        reply = hub.handle('Создай встречу с Иваном завтра в 15:00')
        self.assertIn('«Встреча с Иваном»', reply)
        body = [c for c in hub.http.calls if c[0] == 'POST'][0][2]['json']
        self.assertEqual(body['summary'], 'Встреча с Иваном')
        start = datetime.fromisoformat(body['start']['dateTime'])
        self.assertEqual((start.date(), start.hour), (today + timedelta(days=1), 15))
        self.assertEqual(datetime.fromisoformat(body['end']['dateTime']) - start, timedelta(hours=1))

    def test_google_scope_check_and_incremental_consent(self):
        hub = hub_with()
        docs = connect(hub, 'google_docs', scope='openid https://www.googleapis.com/auth/documents '
                                                 'https://www.googleapis.com/auth/drive.metadata.readonly')
        self.assertTrue(docs.connected())
        self.assertFalse(hub.get('google_calendar').connected())      # старый вход без календаря
        with patch.object(apps.GoogleCalendarConnector, 'client_id', 'cid'):
            url = hub.get('google_calendar').start('http://127.0.0.1:5000/')['url']
        self.assertIn('calendar.events', url)
        self.assertIn('include_granted_scopes=true', url)
        self.assertNotIn('documents', url)

    def test_all_day_event_without_time(self):
        hub = hub_with([('POST', 'calendar/v3', {})])
        connect(hub, 'google_calendar')
        reply = hub.handle('Добавь в календарь день рождения мамы 5 октября')
        self.assertIn('весь день', reply)
        body = hub.http.calls[-1][2]['json']
        self.assertEqual(body['summary'], 'День рождения мамы')
        self.assertIn('date', body['start'])

    def test_create_without_time_asks(self):
        hub = hub_with()
        connect(hub, 'google_calendar')
        self.assertIn('Когда?', hub.handle('Создай встречу с Иваном'))

    def test_yandex_caldav(self):
        today = apps.now().date()
        ics = ('BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Стоматолог\r\n'
               f'DTSTART:{today:%Y%m%d}T090000Z\r\nEND:VEVENT\r\nEND:VCALENDAR')
        principal = ('<d:multistatus xmlns:d="DAV:"><d:response><d:propstat><d:prop><d:current-user-principal>'
                     '<d:href>/principals/me/</d:href></d:current-user-principal></d:prop></d:propstat></d:response></d:multistatus>')
        home = ('<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:propstat><d:prop>'
                '<c:calendar-home-set><d:href>/calendars/me/</d:href></c:calendar-home-set></d:prop></d:propstat>'
                '</d:response></d:multistatus>')
        listing = ('<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                   '<d:response><d:href>/calendars/me/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/>'
                   '</d:resourcetype></d:prop></d:propstat></d:response>'
                   '<d:response><d:href>/calendars/me/todo/</d:href><d:propstat><d:prop><d:resourcetype><c:calendar/>'
                   '</d:resourcetype><c:supported-calendar-component-set><c:comp name="VTODO"/></c:supported-calendar-component-set>'
                   '</d:prop></d:propstat></d:response>'
                   '<d:response><d:href>/calendars/me/events-1/</d:href><d:propstat><d:prop><d:resourcetype><c:calendar/>'
                   '</d:resourcetype><c:supported-calendar-component-set><c:comp name="VEVENT"/></c:supported-calendar-component-set>'
                   '</d:prop></d:propstat></d:response></d:multistatus>')
        report = ('<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:propstat><d:prop>'
                  f'<c:calendar-data>{ics}</c:calendar-data></d:prop></d:propstat></d:response></d:multistatus>')

        def propfind(url, kwargs):
            body = kwargs['data'].decode()
            if 'current-user-principal' in body:
                return Response(None, 207, content=principal.encode())
            if 'calendar-home-set' in body:
                return Response(None, 207, content=home.encode())
            return Response(None, 207, content=listing.encode())
        hub = hub_with([('PROPFIND', 'caldav.yandex.ru', propfind),
                        ('REPORT', 'caldav.yandex.ru', Response(None, 207, content=report.encode())),
                        ('PUT', 'caldav.yandex.ru', Response(None, 201, content=b''))])
        yandex = connect(hub, 'yandex', email='me@yandex.ru')
        reply = hub.handle('Дела на сегодня в Яндекс Календаре')
        self.assertIn('Стоматолог', reply)
        self.assertEqual(yandex.saved()['caldav'], '/calendars/me/events-1/')
        method, url, kwargs = hub.http.calls[-1]
        self.assertEqual(kwargs['headers']['Authorization'], 'OAuth tok')
        hub.handle('Создай в Яндекс Календаре встречу с юристом завтра в 11')
        method, url, kwargs = hub.http.calls[-1]
        self.assertEqual(method, 'PUT')
        self.assertTrue(url.startswith('https://caldav.yandex.ru/calendars/me/events-1/'))
        body = kwargs['data'].decode()
        self.assertIn('SUMMARY:Встреча с юристом', body)
        self.assertIn('DTSTART:', body)


class FakeImap:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.logged = None
        self.literal = None
        FakeImap.instances.append(self)

    def login(self, user, password):
        if password != 'app-pass':
            import imaplib
            raise imaplib.IMAP4.error('AUTHENTICATIONFAILED')
        self.logged = user

    def authenticate(self, mech, callback):
        self.logged = callback(b'').decode()

    def select(self, box, readonly=False):
        return 'OK', [b'3']

    def uid(self, command, *args):
        if command == 'SEARCH':
            self.search_args = args
            return 'OK', [b'5 7 9']
        headers = (b'From: =?utf-8?b?0JjQstCw0L0=?= <ivan@mail.ru>\r\nSubject: =?utf-8?b?0KHRh9C10YI=?=\r\n\r\n')
        return 'OK', [(b'1 (UID 7 BODY[HEADER] {10}', headers), b')', (b'2 (UID 9 BODY[HEADER] {10}',
                                                                         b'From: shop@x.ru\r\nSubject: Sale\r\n\r\n'), b')']

    def logout(self):
        pass


class MailTests(Isolated):
    def setUp(self):
        super().setUp()
        FakeImap.instances.clear()
        patcher = patch.object(apps.Imap, 'factory', FakeImap)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_imap_connect_by_fields_and_summary(self):
        hub = hub_with()
        imap = hub.get('imap')
        with self.assertRaises(connectors.ConnectorError):
            imap.use_fields({'email': 'me@mail.ru', 'password': 'wrong'})
        self.assertFalse(imap.connected())
        self.assertEqual(imap.use_fields({'email': 'me@mail.ru', 'password': 'app-pass'}), 'me@mail.ru')
        self.assertEqual(FakeImap.instances[-1].host, 'imap.mail.ru')
        reply = hub.handle('Прочитай новые письма')
        self.assertIn('3 новых письма', reply)
        self.assertIn('от shop@x.ru: Sale', reply)
        self.assertIn('от Иван: Счет', reply.replace('ё', 'е'))
        self.assertEqual(hub.handle('Сколько новых писем?'), 'В почте 3 новых письма.')

    def test_imap_search_unicode(self):
        hub = hub_with()
        hub.get('imap').use_fields({'email': 'me@gmail.com', 'password': 'app-pass'})
        reply = hub.handle('Найди письмо от Ивана')
        self.assertIn('Нашёл писем: 2', reply)
        box = FakeImap.instances[-1]
        self.assertEqual(box.search_args, ('CHARSET', 'UTF-8', 'FROM'))
        self.assertEqual(box.literal, 'Ивана'.encode())

    def test_gmail_unread(self):
        hub = hub_with([('GET', 'labels/INBOX', {'messagesUnread': 1}),
                        ('GET', '/messages/m1', {'payload': {'headers': [{'name': 'From', 'value': 'Анна <a@b.ru>'},
                                                                         {'name': 'Subject', 'value': 'Отчёт'}]}}),
                        ('GET', '/messages', {'messages': [{'id': 'm1'}]})])
        connect(hub, 'gmail')
        self.assertEqual(hub.handle('Прочитай новые письма в Gmail'), 'В Gmail 1 новое письмо: от Анна: Отчёт.')

    def test_yandex_mail_uses_xoauth2(self):
        hub = hub_with()
        connect(hub, 'yandex', email='me@yandex.ru')
        self.assertIn('3 новых письма', hub.handle('Сколько новых писем в Яндекс Почте?'))
        box = FakeImap.instances[-1]
        self.assertEqual(box.host, 'imap.yandex.ru')
        self.assertEqual(box.logged, 'user=me@yandex.ru\x01auth=Bearer tok\x01\x01')


class TaskTests(Isolated):
    def test_named_but_not_connected(self):
        hub = hub_with()
        reply = hub.handle('Добавь в Notion задачу подготовить отчёт', named_only=True)
        self.assertIn('Notion не подключён', reply)
        self.assertIsNone(hub.handle('Какая погода завтра?'))

    def test_notion_add_and_list(self):
        base = {'results': [{'id': 'db2', 'title': [{'plain_text': 'Заметки'}], 'properties': {}},
                            {'id': 'db1', 'title': [{'plain_text': 'Мои задачи'}],
                             'properties': {'Name': {'type': 'title'}, 'Готово': {'type': 'checkbox'},
                                            'Срок': {'type': 'date'}}}]}
        pages = {'results': [{'properties': {'Name': {'title': [{'plain_text': 'Позвонить'}]},
                                             'Срок': {'date': {'start': str(apps.now().date())}}}}]}
        hub = hub_with([('POST', '/v1/search', base), ('POST', '/databases/db1/query', pages), ('POST', '/v1/pages', {})])
        connect(hub, 'notion')
        reply = hub.handle('Добавь в Notion задачу подготовить отчёт на завтра')
        self.assertEqual(reply, 'Добавил в Notion задачу «Подготовить отчёт» на завтра.')
        body = hub.http.calls[-1][2]['json']
        self.assertEqual(body['parent'], {'database_id': 'db1'})
        self.assertEqual(body['properties']['Name']['title'][0]['text']['content'], 'Подготовить отчёт')
        self.assertIn('Срок', body['properties'])
        self.assertEqual(hub.http.calls[-1][2]['headers']['Notion-Version'], '2022-06-28')
        reply = hub.handle('Что в моём списке дел в Notion?')
        self.assertIn('1 задача: Позвонить', reply)
        query = [c for c in hub.http.calls if 'query' in c[1]][0][2]['json']
        self.assertEqual(query['filter'], {'property': 'Готово', 'checkbox': {'equals': False}})

    def test_todoist_generic_add_list_done(self):
        tasks = {'results': [{'id': '1', 'content': 'Купить молоко', 'due': {'date': str(apps.now().date())}}]}
        hub = hub_with([('GET', '/tasks/filter', tasks), ('POST', '/tasks/1/close', {}), ('POST', '/api/v1/tasks', {})])
        connect(hub, 'todoist')
        reply = hub.handle('Добавь задачу позвонить маме завтра в 18:00')
        self.assertIn('Todoist', reply)
        self.assertIn('«Позвонить маме» на завтра в 18:00', reply)
        body = [c for c in hub.http.calls if c[0] == 'POST'][-1][2]['json']
        self.assertEqual(body['content'], 'Позвонить маме')
        self.assertTrue(body['due_datetime'].endswith('Z'))
        self.assertIn('Купить молоко', hub.handle('Что в моём списке дел?'))
        self.assertEqual(hub.handle('Отметь задачу купить молоко'), 'Отметил выполненной: «Купить молоко».')
        self.assertEqual(hub.http.calls[-1][1], 'https://api.todoist.com/api/v1/tasks/1/close')

    def test_task_for_repository_is_not_taken(self):
        hub = hub_with()
        connect(hub, 'todoist')
        self.assertIsNone(hub.get('todoist').handle('Создай задачу в репозитории ai_agent: не работает звук'))

    def test_yougile_key_from_login(self):
        hub = hub_with([('POST', '/auth/companies', {'content': [{'id': 'c1', 'name': 'Моя фирма'}]}),
                        ('POST', '/auth/keys', {'key': 'KEY'}), ('GET', '/columns', {'content': [{'id': 'col'}]}),
                        ('POST', '/api-v2/tasks', {'id': 't'})])
        yougile = hub.get('yougile')
        self.assertEqual(yougile.use_fields({'login': 'a@b.ru', 'password': 'p'}), 'Моя фирма')
        self.assertEqual(yougile.saved()['access_token'], 'KEY')
        self.assertNotIn('password', json.dumps(yougile.saved()))
        hub.handle('Добавь в YouGile задачу обновить прайс')
        self.assertEqual(hub.http.calls[-1][2]['json'], {'title': 'Обновить прайс', 'columnId': 'col'})

    def test_weeek_and_kaiten(self):
        hub = hub_with([('GET', '/tm/tasks', {'tasks': [{'title': 'Оплатить хостинг', 'isCompleted': False}]}),
                        ('GET', '/users/current', {'id': 5, 'full_name': 'Ира'}),
                        ('GET', '/cards', [{'title': 'Макет', 'due_date': None}])])
        connect(hub, 'weeek')
        self.assertIn('Оплатить хостинг', hub.handle('Что в Weeek на сегодня?'))
        kaiten = hub.get('kaiten')
        self.assertEqual(kaiten.use_fields({'domain': 'https://firm.kaiten.ru/space/1', 'token': 'k'}), 'Ира')
        self.assertEqual(kaiten.saved()['domain'], 'firm.kaiten.ru')
        self.assertIn('Макет', hub.handle('Мои задачи в Kaiten'))
        self.assertEqual(hub.http.calls[-1][2]['params']['member_ids'], 5)


class FilesTests(Isolated):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / 'Договор.pdf'
        self.file.write_bytes(b'%PDF-1.4 test')
        self.documents = MagicMock()
        self.documents.target.return_value = [self.file]

    def test_yandex_disk_upload(self):
        hub = hub_with([('PUT', 'v1/disk/resources', Response({}, 201)),
                        ('GET', 'resources/upload', {'href': 'https://uploader/put'}),
                        ('PUT', 'uploader/put', Response({}, 201))], documents=self.documents)
        connect(hub, 'yandex')
        self.assertEqual(hub.handle('Загрузи этот файл на Яндекс Диск', named_only=True),
                         'Загрузил «Договор.pdf» на Яндекс Диск в папку «Андрей».')
        upload = hub.http.calls[-1]
        self.assertEqual(upload[1], 'https://uploader/put')
        self.assertNotIn('headers', upload[2])       # подписанная ссылка — без токена
        params = [c for c in hub.http.calls if 'resources/upload' in c[1]][0][2]['params']
        self.assertEqual(params['path'], 'disk:/Андрей/Договор.pdf')

    def test_generic_disk_goes_to_connected_cloud(self):
        hub = hub_with([('POST', 'files/upload', {})], documents=self.documents)
        connect(hub, 'dropbox')
        self.assertIn('Dropbox', hub.handle('Загрузи этот файл на диск'))
        arg = json.loads(hub.http.calls[-1][2]['headers']['Dropbox-API-Arg'])
        self.assertEqual(arg, {'path': '/Андрей/Договор.pdf', 'mode': 'add', 'autorename': True})
        self.assertTrue(hub.http.calls[-1][2]['headers']['Dropbox-API-Arg'].isascii())

    def test_dropbox_find_and_space(self):
        hub = hub_with([('POST', 'search_v2', {'matches': [{'metadata': {'metadata': {'name': 'Договор.pdf',
                                                                                      'path_display': '/Работа/Договор.pdf'}}}]}),
                        ('POST', 'get_space_usage', {'used': 2 * 2 ** 30, 'allocation': {'allocated': 2 * 2 ** 40}})])
        connect(hub, 'dropbox')
        self.assertIn('/Работа/Договор.pdf', hub.handle('Найди в Dropbox договор'))
        self.assertTrue(hub.opened[-1].startswith('https://www.dropbox.com/home/'))
        self.assertIn('занято 2 ГБ из 2 ТБ', hub.handle('Сколько места в Dropbox?'))

    def test_onedrive_upload_and_microsoft_localhost_redirect(self):
        hub = hub_with([('PUT', 'drive/root:', {})], documents=self.documents)
        connect(hub, 'microsoft')
        self.assertIn('OneDrive', hub.handle('Загрузи этот файл в OneDrive'))
        self.assertIn('/me/drive/root:/%D0%90%D0%BD%D0%B4%D1%80%D0%B5%D0%B9/', hub.http.calls[-1][1])
        ms = hub.get('microsoft')
        self.assertEqual(ms.redirect_uri('http://127.0.0.1:5000/'), 'http://localhost:5000/oauth/microsoft/callback')

    def test_no_selected_file(self):
        self.documents.target.return_value = []
        hub = hub_with(documents=self.documents)
        connect(hub, 'dropbox')
        self.assertIn('Не вижу файла', hub.handle('Загрузи этот файл в Dropbox'))


class MicrosoftTests(Isolated):
    def test_outlook_calendar_mail_todo(self):
        today = apps.now().date()
        start = datetime.combine(today, datetime.min.time()).astimezone().astimezone(apps.timezone.utc) + timedelta(hours=12)
        hub = hub_with([('GET', 'calendarView', {'value': [{'subject': 'Созвон', 'isAllDay': False,
                                                             'start': {'dateTime': start.strftime('%Y-%m-%dT%H:%M:%S.0000000')}}]}),
                        ('GET', 'mailFolders/inbox/messages', {'value': [{'from': {'emailAddress': {'name': 'Босс'}},
                                                                          'subject': 'Срочно'}]}),
                        ('GET', 'mailFolders/inbox', {'unreadItemCount': 2}),
                        ('GET', 'todo/lists', {'value': [{'id': 'L', 'wellknownListName': 'defaultList'}]}),
                        ('POST', 'todo/lists/L/tasks', {})])
        connect(hub, 'microsoft')
        self.assertIn('Созвон', hub.handle('Что у меня сегодня в календаре Outlook?'))
        self.assertIn('от Босс: Срочно', hub.handle('Прочитай новые письма в Outlook'))
        self.assertIn('To Do', hub.handle('Добавь в To Do задачу купить билеты на пятницу'))
        body = hub.http.calls[-1][2]['json']
        self.assertEqual(body['title'], 'Купить билеты')
        self.assertTrue(body['dueDateTime']['dateTime'].endswith('T00:00:00'))


class InvestTests(Isolated):
    def routes(self):
        portfolio = {'totalAmountPortfolio': {'currency': 'rub', 'units': '150000', 'nano': 0},
                     'expectedYield': {'units': '12', 'nano': 500000000},
                     'dailyYield': {'currency': 'rub', 'units': '-1500', 'nano': 0},
                     'positions': [{'instrumentType': 'share', 'ticker': 'SBER', 'dailyYield': {'units': '-1200', 'nano': 0}},
                                   {'instrumentType': 'share', 'figi': 'F2', 'instrumentUid': 'u2',
                                    'dailyYield': {'units': '-300', 'nano': 0}},
                                   {'instrumentType': 'currency', 'ticker': 'RUB000UTSTOM', 'dailyYield': {}}]}
        return [('POST', 'GetAccounts', {'accounts': [{'id': 'a1', 'status': 'ACCOUNT_STATUS_OPEN'}]}),
                ('POST', 'GetPortfolio', portfolio),
                ('POST', 'GetInstrumentBy', {'instrument': {'name': 'Газпром'}})]

    def test_portfolio_value_and_daily(self):
        hub = hub_with(self.routes())
        hub.get('tinvest').use_fields({'token': 't.readonly'})
        self.assertEqual(hub.handle('Сколько стоит мой портфель?'),
                         'Портфель стоит 150 000 ₽. Доходность за всё время: +12.50%.')
        reply = hub.handle('Как изменились акции за день?')
        self.assertIn('снизился на 1 500 ₽', reply)
        self.assertIn('SBER −1 200 ₽', reply)
        self.assertIn('Газпром −300 ₽', reply)

    def test_never_trades(self):
        hub = hub_with(self.routes())
        connect(hub, 'tinvest')
        self.assertIn('не буду', hub.handle('Купи акции Сбербанка в Т-Инвестициях'))
        self.assertFalse([c for c in hub.http.calls if 'PostOrder' in c[1]])


class CrmTests(Isolated):
    def test_bitrix_webhook_deals_and_contact(self):
        url = 'https://firm.bitrix24.ru/rest/1/abc123/'
        hub = hub_with([('POST', 'profile.json', {'result': {'NAME': 'Олег', 'LAST_NAME': 'Иванов'}}),
                        ('POST', 'crm.deal.list.json', {'result': [{'ID': '7', 'TITLE': 'Сайт', 'OPPORTUNITY': '50000.00',
                                                                    'CURRENCY_ID': 'RUB'}], 'total': 1}),
                        ('POST', 'crm.contact.add.json', {'result': 11})])
        bitrix = hub.get('bitrix24')
        with self.assertRaises(connectors.ConnectorError):
            bitrix.use_fields({'webhook': 'https://example.com'})
        self.assertEqual(bitrix.use_fields({'webhook': url.rstrip('/')}), 'Олег Иванов')
        self.assertEqual(hub.handle('Новые сделки'), 'Новых сделок за неделю в Битрикс24: 1. Сайт — 50 000 ₽.')
        self.assertNotIn('Authorization', hub.http.calls[-1][2]['headers'])
        self.assertIn('Добавил клиента «Иван Петров»', hub.handle('Добавь клиента Иван Петров телефон 8 999 123-45-67'))
        fields = hub.http.calls[-1][2]['json']['fields']
        self.assertEqual((fields['NAME'], fields['LAST_NAME']), ('Иван', 'Петров'))
        self.assertEqual(fields['PHONE'], [{'VALUE': '+79991234567', 'VALUE_TYPE': 'WORK'}])

    def test_amocrm(self):
        hub = hub_with([('GET', '/account', {'name': 'Фирма'}),
                        ('GET', '/leads', {'_embedded': {'leads': [{'name': 'Заявка с сайта', 'price': 12000}]}}),
                        ('POST', '/contacts', [{}])])
        amo = hub.get('amocrm')
        self.assertEqual(amo.use_fields({'domain': 'firm', 'token': 'long'}), 'Фирма')
        self.assertEqual(amo.saved()['domain'], 'firm.amocrm.ru')
        self.assertIn('Заявка с сайта — 12 000 ₽', hub.handle('Новые сделки в амо'))
        hub.handle('Добавь клиента Анна Смирнова anna@mail.ru')
        body = hub.http.calls[-1][2]['json'][0]
        self.assertEqual(body['name'], 'Анна Смирнова')
        self.assertEqual(body['custom_fields_values'][0]['field_code'], 'EMAIL')


class SpotifyTests(Isolated):
    def test_playlist_now_playing_and_premium(self):
        hub = hub_with([('GET', '/me/playlists', {'items': [{'name': 'Утро', 'uri': 'spotify:playlist:1'},
                                                             {'name': 'Для бега', 'uri': 'spotify:playlist:2'}]}),
                        ('PUT', '/me/player/play', {}),
                        ('GET', 'currently-playing', {'item': {'name': 'Believer', 'artists': [{'name': 'Imagine Dragons'}]}})])
        connect(hub, 'spotify')
        self.assertEqual(hub.handle('Включи мой плейлист для бега'), 'Включаю плейлист «Для бега».')
        self.assertEqual(hub.http.calls[-1][2]['json'], {'context_uri': 'spotify:playlist:2'})
        self.assertEqual(hub.handle('Что сейчас играет?'), 'Сейчас играет: Imagine Dragons — «Believer».')
        hub.http.routes.insert(0, ('POST', '/me/player/next', Response({'error': {'message': 'Premium required'}}, 403)))
        self.assertIn('Premium', hub.handle('Следующий трек в Spotify'))

    def test_no_device_opens_app(self):
        hub = hub_with([('GET', '/me/playlists', {'items': [{'name': 'Утро', 'uri': 'spotify:playlist:1'}]}),
                        ('PUT', '/me/player/play', Response({'error': {'reason': 'NO_ACTIVE_DEVICE'}}, 404)),
                        ('GET', '/me/player/devices', {'devices': []})])
        connect(hub, 'spotify')
        self.assertIn('нажмите «Play»', hub.handle('Включи плейлист утро'))
        self.assertEqual(hub.opened, ['spotify:playlist:1'])


class DevTests(Isolated):
    def test_gitlab_merge_requests(self):
        hub = hub_with([('GET', '/merge_requests', [{'id': 1, 'iid': 4, 'title': 'Новый дизайн'}]),
                        ('GET', '/user', {'username': 'ira'})])
        gitlab = hub.get('gitlab')
        self.assertEqual(gitlab.use_fields({'token': 'glpat', 'url': ''}), 'ira')
        self.assertEqual(hub.handle('Мои merge request в GitLab'), 'Открытых merge request: 1. !4 Новый дизайн.')
        self.assertTrue(hub.http.calls[-1][1].startswith('https://gitlab.com/api/v4/'))

    def test_jira_basic_auth_and_search(self):
        hub = hub_with([('GET', '/search/jql', {'issues': [{'key': 'WEB-1', 'fields': {'summary': 'Форма', 'status': {'name': 'В работе'}}}]}),
                        ('GET', '/myself', {'displayName': 'Ира'})])
        jira = hub.get('jira')
        jira.use_fields({'site': 'firm.atlassian.net', 'email': 'ira@firm.ru', 'token': 'T'})
        self.assertEqual(hub.handle('Мои задачи в Jira'), 'Ваши задачи в Jira: 1. WEB-1 Форма (В работе).')
        self.assertTrue(hub.http.calls[-1][2]['headers']['Authorization'].startswith('Basic '))
        self.assertIn('/rest/api/3/search/jql', hub.http.calls[-1][1])

    def test_linear_create(self):
        def graphql(url, kwargs):
            query = kwargs['json']['query']
            if 'teams' in query:
                return {'data': {'teams': {'nodes': [{'id': 'T1', 'name': 'Core', 'key': 'COR'}]}}}
            return {'data': {'issueCreate': {'success': True, 'issue': {'identifier': 'COR-9', 'url': 'u'}}}}
        hub = hub_with([('POST', 'api.linear.app', graphql)])
        connect(hub, 'linear')
        self.assertEqual(hub.handle('Создай задачу в Linear: починить вход по почте'),
                         'Создал задачу COR-9 в Linear: Починить вход по почте.')
        self.assertEqual(hub.http.calls[-1][2]['headers']['Authorization'], 'tok')

    def test_dev_needs_name(self):
        hub = hub_with()
        connect(hub, 'jira')
        self.assertIsNone(hub.get('jira').handle('Мои задачи'))


class ApiTests(Isolated):
    def test_status_has_fields_and_groups(self):
        hub = hub_with()
        items = {i['id']: i for i in hub.status()}
        self.assertEqual([f['name'] for f in items['imap']['fields']], ['email', 'password', 'server'])
        self.assertTrue(items['imap']['fields'][2]['optional'])
        self.assertEqual(items['github']['fields'][0]['name'], 'token')   # запасной вход по токену
        self.assertEqual(items['tinvest']['group'], 'Финансы')
        self.assertEqual(items['todoist']['auth'], 'token')
        self.assertFalse(items['spotify']['fields'])

    def test_connect_endpoint_with_fields(self):
        from app import create_app
        from src.storage import Store as RealStore
        store = RealStore(tempfile.mkdtemp())
        application = create_app(store, MagicMock(status=MagicMock(return_value={})), MagicMock(),
                                 license=MagicMock(is_premium=lambda: True))
        client = application.test_client()
        headers = {'X-Agent-Token': store.meta('pairing_token')}
        with patch.object(apps.TodoistConnector, 'whoami_with', lambda self, saved: 'Ира'):
            response = client.post('/api/connectors/todoist/connect', json={'fields': {'token': 'T'}}, headers=headers)
        self.assertEqual(response.get_json(), {'success': True, 'connected': True, 'user': 'Ира'})
        response = client.post('/api/connectors/imap/connect', json={'fields': {'email': 'a@b.ru'}}, headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Пароль приложения', response.get_json()['message'])


class HomeAssistantTests(unittest.TestCase):
    STATES = [
        {'entity_id': 'climate.bedroom', 'state': 'cool', 'attributes': {'friendly_name': 'Кондиционер спальня', 'temperature': 22}},
        {'entity_id': 'climate.living', 'state': 'off', 'attributes': {'friendly_name': 'Кондиционер гостиная'}},
        {'entity_id': 'sensor.kids_t', 'state': '23.4', 'attributes': {'friendly_name': 'Детская температура',
                                                                       'device_class': 'temperature', 'unit_of_measurement': '°C'}},
        {'entity_id': 'sensor.kids_h', 'state': '41', 'attributes': {'friendly_name': 'Детская влажность',
                                                                     'device_class': 'humidity', 'unit_of_measurement': '%'}},
        {'entity_id': 'binary_sensor.leak', 'state': 'on', 'attributes': {'friendly_name': 'Ванная', 'device_class': 'moisture'}},
        {'entity_id': 'vacuum.robo', 'state': 'docked', 'attributes': {'friendly_name': 'Робот', 'battery_level': 90}},
        {'entity_id': 'camera.door', 'state': 'idle', 'attributes': {'friendly_name': 'Дверь'}},
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.session = MagicMock()
        self.session.get.side_effect = lambda url, **kw: Response(self.STATES, url=url) if url.endswith('/api/states') else \
            Response(None, content=b'\xff\xd8jpeg', url=url)
        self.session.post.return_value = Response({})
        self.home = SmartHome(Store(self.tmp.name), session=self.session)
        self.home.save('lights', {'ha_url': 'http://ha.local:8123', 'ha_token': 'T'})

    def posted(self):
        url = self.session.post.call_args[0][0]
        return url.split('/api/services/')[1], self.session.post.call_args[1]['json']

    def test_climate(self):
        self.assertEqual(self.home.handle('Включи кондиционер в спальне'), 'Включаю кондиционер (спальне).')
        self.assertEqual(self.posted(), ('climate/turn_on', {'entity_id': ['climate.bedroom']}))
        self.assertEqual(self.home.handle('Поставь кондиционер в спальне на 24'), 'Ставлю 24 °C (спальне).')
        self.assertEqual(self.posted()[1]['temperature'], 24)
        self.assertEqual(self.home.handle('Сделай теплее в спальне'), 'Ставлю 23 °C (спальне).')
        self.home.handle('Режим охлаждения на кондиционере')
        self.assertEqual(self.posted(), ('climate/set_hvac_mode', {'entity_id': ['climate.bedroom', 'climate.living'],
                                                                   'hvac_mode': 'cool'}))

    def test_sensors(self):
        self.assertEqual(self.home.handle('Какая температура в детской?'), 'Детская температура: 23.4 °C.')
        reply = self.home.handle('Что показывают датчики?')
        self.assertIn('Детская влажность: 41 %', reply)
        self.assertIn('Ванная: ПРОТЕЧКА', reply)
        self.assertIsNone(self.home.handle('Какая температура на улице?'))

    def test_vacuum(self):
        self.assertEqual(self.home.handle('Запусти пылесос'), 'Запускаю уборку.')
        self.assertEqual(self.posted(), ('vacuum/start', {'entity_id': ['vacuum.robo']}))
        self.home.handle('Верни пылесос на базу')
        self.assertEqual(self.posted()[0], 'vacuum/return_to_base')
        self.assertEqual(self.home.handle('Что с пылесосом?'), 'Робот: на базе, заряд 90%.')

    def test_camera_snapshot_to_chat(self):
        self.home.documents = MagicMock()
        self.assertEqual(self.home.handle('Покажи камеру у двери'), 'Показываю камеру «Дверь».')
        path = self.home.documents.publish.call_args[0][0]
        self.assertEqual(path.read_bytes(), b'\xff\xd8jpeg')
        self.assertEqual(path.parent.name, 'Камеры')

    def test_parse_home_ignores_weather(self):
        self.assertIsNone(parse_home('Какая температура завтра в Москве?'))
        self.assertIsNone(parse_home('Какая температура?'))


if __name__ == '__main__':
    unittest.main()
