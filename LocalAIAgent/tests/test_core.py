import io
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from app import create_app
from src.storage import Store
from src.agent import parse_command, LocalComputerAgent
from src.app_control import targets, normalize
from src.browser_control import BrowserController
from src.speech import SpeechService, SpeechError, decode


class RoutingTests(unittest.TestCase):
    def test_open_app(self):
        self.assertEqual(parse_command('Открой калькулятор'), ('open_app','калькулятор'))
    def test_close_before_search(self):
        self.assertEqual(parse_command('Закрой приложение Chrome.'), ('close_app','приложение Chrome'))
    def test_pause_not_launch(self):
        self.assertEqual(parse_command('Останови видео')[0], 'pause')
    def test_close_tab(self):
        self.assertEqual(parse_command('Закрой вкладку')[0], 'close_tab')
    def test_resume(self):
        self.assertEqual(parse_command('Продолжи видео')[0], 'play')
    def test_wake_name(self):
        self.assertEqual(parse_command('Андрей, открой калькулятор')[0], 'open_app')
    def test_custom_wake(self):
        self.assertEqual(parse_command('Алиса, пауза видео', {'wake_word':'Алиса'})[0], 'pause')
    def test_mass_close_disabled(self):
        self.assertEqual(parse_command('Закрой все приложения')[0], 'refuse_mass')
    def test_aliases(self):
        self.assertEqual(targets('приложение Хром'), ['chrome.exe'])
        self.assertIn('calculatorapp.exe',targets('калькулятор'))
    def test_shell_text_not_a_target(self):
        self.assertEqual(targets('chrome & shutdown /s'), [])
    def test_url_validation(self):
        for url in ['file:///c:/', 'javascript:alert(1)', 'https://user:pass@example.com']:
            with self.assertRaises(ValueError):BrowserController.valid_url(url)
        self.assertEqual(BrowserController.valid_url('https://example.com'), 'https://example.com')
    def test_rutube_routing(self):
        browser=Mock();agent=LocalComputerAgent(browser)
        agent.process_command('Включи видео котики на Rutube')
        browser.call.assert_called_once_with('video','котики','rutube')
    def test_direct_video(self):
        browser=Mock();LocalComputerAgent(browser).process_command('Открой видео https://example.com/test.mp4')
        browser.call.assert_called_once_with('video','https://example.com/test.mp4','youtube')
    def test_old_youtube_phrase(self):
        browser=Mock();LocalComputerAgent(browser).process_command('Открой ютуб и запусти песню AC/DC')
        browser.call.assert_called_once_with('video','AC/DC','youtube')
    def test_unknown(self):
        self.assertEqual(parse_command('случайный шум')[0],'unknown')


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.agent=Mock();self.agent.process_command.return_value='Выполнено'
        self.speech=Mock();self.speech.status.return_value={'ready':True}
        self.speech.transcribe.return_value={'text':'открой калькулятор','empty':False}
        self.app=create_app(self.store,self.speech,self.agent)
        self.client=self.app.test_client()
        self.headers={'X-Agent-Token':self.store.meta('pairing_token'),'X-Device-ID':'desktop'}
    def tearDown(self):self.temp.cleanup()
    def post(self,route,body):return self.client.post('/api/'+route,json=body,headers=self.headers)
    def test_auth(self):
        self.assertEqual(self.client.get('/api/history').status_code,401)
        self.assertEqual(self.client.get('/health').status_code,200)
    def test_cross_origin(self):
        self.assertEqual(self.client.get('/api/history',headers=dict(self.headers,Origin='https://evil.example')).status_code,403)
    def test_settings_persist(self):
        self.assertEqual(self.post('settings',{'microphone':'mic-123','auto_send':False}).status_code,200)
        fresh=Store(self.temp.name)
        self.assertEqual(fresh.settings('device:desktop')['microphone'],'mic-123')
        self.assertFalse(fresh.settings('device:desktop')['auto_send'])
    def test_settings_validation(self):
        self.assertEqual(self.post('settings',{'auto_send':'false'}).status_code,400)
        self.assertEqual(self.post('settings',{'silence_ms':-1}).status_code,400)
    def test_deduplicate(self):
        body={'id':'test-command-0001','message':'Открой калькулятор'}
        self.assertEqual(self.post('chat',body).status_code,200)
        self.assertTrue(self.post('chat',body).json['duplicate'])
        self.assertEqual(self.agent.process_command.call_count,1)
        self.assertEqual(len(self.store.history('device:desktop')),2)
    def test_id_required(self):
        self.assertEqual(self.post('chat',{'message':'Открой Chrome'}).status_code,400)
    def test_persistent_dedup(self):
        body={'id':'test-command-0002','message':'Пауза видео'}
        self.post('chat',body)
        fresh=create_app(Store(self.temp.name),self.speech,self.agent).test_client()
        self.assertTrue(fresh.post('/api/chat',json=body,headers=self.headers).json['duplicate'])
    def test_profiles(self):
        self.assertEqual(self.post('register',{'name':'tester','password':'my-test-password'}).status_code,200)
        self.assertEqual(self.post('login',{'name':'tester','password':'bad'}).status_code,401)
        self.assertEqual(self.post('login',{'name':'tester','password':'my-test-password'}).status_code,200)
        self.post('settings',{'microphone':'account-mic'})
        self.assertEqual(self.store.settings('user:tester')['microphone'],'account-mic')
        self.post('logout',{})
        self.assertEqual(self.client.get('/api/settings',headers=self.headers).json['settings']['microphone'],'')
    def test_transcribe(self):
        res=self.client.post('/api/transcribe',headers=self.headers,data={'audio':(io.BytesIO(b'audio'),'test.wav'),'language':'ru'})
        self.assertEqual(res.json['text'],'открой калькулятор')
        self.speech.transcribe.assert_called_once_with(b'audio','ru')
    def test_transcribe_missing(self):
        self.assertEqual(self.post('transcribe',{}).status_code,400)
    def test_history_clear(self):
        self.store.add('device:desktop','user','hello')
        self.assertEqual(self.post('history/clear',{}).status_code,200)
        self.assertEqual(self.store.history('device:desktop'),[])
    def test_token_persistent(self):
        self.assertEqual(Store(self.temp.name).meta('pairing_token'),self.store.meta('pairing_token'))
    def test_page_assets(self):
        html=self.client.get('/').text
        self.assertEqual(html.count('/static/speech.js'),1)
        self.assertEqual(html.count('/static/app.js'),1)
        settings=self.client.get('/settings').text
        self.assertIn('/static/settings.js',settings)
        with self.client.get('/static/themes.css') as response:
            css=response.text
        for theme in ('aurora','cyberpunk','sakura','ocean','luxe'):
            self.assertIn('[data-theme="'+theme+'"]',css)
        with self.client.get('/static/icon-192.png') as response:
            self.assertEqual(response.status_code,200)


def wav(seconds=1,rate=44100,channels=2):
    buf=io.BytesIO()
    with wave.open(buf,'wb') as w:
        w.setnchannels(channels);w.setsampwidth(2);w.setframerate(rate)
        w.writeframes(b'\0\0'*int(seconds*rate)*channels)
    return buf.getvalue()


class FakeEngine:
    def __init__(self, text=' привет '):
        self.model = object()
        self.text = text
        self.calls = []
    def transcribe(self, audio, language):
        self.calls.append((len(audio), language))
        return self.text, 'ru'


def ready_service(text=' привет '):
    rec = SpeechService(Path('/nonexistent'))
    rec.engines = {'parakeet': FakeEngine(text)}
    rec.engine_key = 'parakeet'
    return rec


class SpeechTests(unittest.TestCase):
    def test_decode_resamples(self):
        audio=decode(wav())
        self.assertEqual(len(audio),16000)
        self.assertEqual(str(audio.dtype),'float32')
    def test_invalid_audio(self):
        with self.assertRaises(SpeechError):decode(b'not an audio file')
    def test_long_audio_rejected(self):
        with self.assertRaises(SpeechError):decode(wav(47,16000,1))
    def test_single_model_inference(self):
        rec=ready_service()
        result=rec.transcribe(wav())
        self.assertEqual(result['text'],'привет')
        self.assertEqual(result['engine'],'parakeet')
        self.assertEqual(rec.engine.calls[0],(16000,'ru'))
    def test_filler_is_empty(self):
        self.assertTrue(ready_service('Угу.').transcribe(wav())['empty'])
    def test_busy(self):
        rec=ready_service();rec.busy=Mock();rec.busy.acquire.return_value=False
        with self.assertRaises(SpeechError) as ctx:rec.transcribe(wav())
        self.assertEqual(ctx.exception.code,429)
    def test_lock_released_on_bad_audio(self):
        rec=ready_service()
        with self.assertRaises(SpeechError):rec.transcribe(b'bad')
        self.assertTrue(rec.busy.acquire(blocking=False))
    def test_language_invalid(self):
        with self.assertRaises(SpeechError):ready_service().transcribe(wav(),'xx')
    def test_not_ready_reports_503(self):
        rec=SpeechService(Path('/nonexistent'))
        rec.error='Модели распознавания не установлены.'
        with self.assertRaises(SpeechError) as ctx:rec.transcribe(wav())
        self.assertEqual(ctx.exception.code,503)


if __name__=='__main__':unittest.main()
