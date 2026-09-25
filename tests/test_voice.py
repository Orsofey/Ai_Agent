"""Голосовой цикл: имя, ожидание команды, горячая клавиша, эхо, диктовка; VAD и потоковая озвучка."""
import tempfile
import time
import unittest
from unittest.mock import Mock
import numpy as np
from src.events import EventBus
from src.speech.vad import Segmenter, StreamingVad
from src.speech.voice_loop import VoiceAssistant
from src.speech.engines import choose_engine
from src.tts_player import SentenceSpeaker, readable
from src.service import AssistantService
from src.storage import Store


class FakeSpeech:
    def __init__(self, *texts):
        self.texts = list(texts)
    def transcribe_array(self, audio, language):
        return {'text': self.texts.pop(0), 'elapsed': 0.12, 'engine': 'parakeet'}
    def vad_dir(self):
        return None


class FakePlayer:
    def __init__(self):
        self.speaking = False
        self.last_end = 0.0
        self.token = 0
        self.stopped = 0
        self.beeps = []
        self.said = []
        self.available = True
    def stop(self):
        self.stopped += 1
        self.token += 1
    def beep(self, kind='wake'):
        self.beeps.append(kind)
    def is_busy(self):
        return False
    def new_utterance(self):
        self.stop()
        return self.token
    def say(self, text, settings, token=None):
        self.said.append(text)
    def acknowledge(self, text, settings):
        self.said.append(text)


def assistant(*texts, settings=None, dictation=False):
    service = Mock()
    service.run.return_value = ('ok', True)
    commands = Mock()
    commands.dictation = dictation
    player = FakePlayer()
    values = dict({'wake_word': 'Андрей', 'wake_aliases': '', 'voice_language': 'auto', 'follow_up_seconds': 0}, **(settings or {}))
    voice = VoiceAssistant(FakeSpeech(*texts), service, EventBus(), lambda: values, player=player, desktop_commands=commands)
    return voice, service, player, commands


AUDIO = np.zeros(16000, dtype=np.float32)


class VoiceLoopTests(unittest.TestCase):
    def test_name_and_command_in_one_phrase(self):
        voice, service, player, _ = assistant('Андрей, напиши текст привет Милана')
        voice.handle_segment(AUDIO)
        self.assertEqual(service.run.call_args.args[0], 'напиши текст привет Милана')
        self.assertEqual(service.run.call_args.kwargs['source'], 'voice')

    def test_ignores_speech_without_name(self):
        voice, service, _, _ = assistant('просто разговор в комнате')
        voice.handle_segment(AUDIO)
        service.run.assert_not_called()

    def test_name_then_command(self):
        voice, service, player, _ = assistant('Андрей', 'какой курс доллара')
        voice.handle_segment(AUDIO)
        self.assertEqual(player.beeps, ['wake'])
        service.run.assert_not_called()
        voice.handle_segment(AUDIO)
        self.assertEqual(service.run.call_args.args[0], 'какой курс доллара')

    def test_hotkey_listen_once(self):
        voice, service, player, _ = assistant('открой калькулятор')
        voice.start = lambda: None
        voice.listen_once()
        voice.handle_segment(AUDIO)
        self.assertEqual(service.run.call_args.args[0], 'открой калькулятор')

    def test_own_voice_echo_is_ignored(self):
        voice, service, player, _ = assistant('открой калькулятор')
        player.speaking = True
        voice.follow_up_until = time.monotonic() + 10
        voice.handle_segment(AUDIO, started=time.monotonic())
        service.run.assert_not_called()

    def test_barge_in_with_name(self):
        voice, service, player, _ = assistant('Андрей, стоп')
        player.speaking = True
        voice.handle_segment(AUDIO, started=time.monotonic())
        self.assertGreaterEqual(player.stopped, 1)
        # «Стоп» не ставится в очередь, а сразу прерывает текущую команду.
        service.cancel.assert_called_once()
        service.run.assert_not_called()

    def test_barge_in_with_other_command(self):
        voice, service, player, _ = assistant('Андрей, открой калькулятор')
        player.speaking = True
        voice.handle_segment(AUDIO, started=time.monotonic())
        self.assertGreaterEqual(player.stopped, 1)
        self.assertEqual(service.run.call_args.args[0], 'открой калькулятор')

    def test_dictation_types_everything(self):
        voice, service, player, commands = assistant('Привет запятая как дела', dictation=True)
        voice.handle_segment(AUDIO)
        commands.desktop.type_text.assert_called_once()
        self.assertEqual(commands.desktop.type_text.call_args.args[0], 'Привет, как дела ')
        service.run.assert_not_called()

    def test_dictation_stop_command(self):
        voice, service, player, commands = assistant('стоп диктовка', dictation=True)
        voice.handle_segment(AUDIO)
        self.assertEqual(service.run.call_args.args[0], 'стоп диктовка')


class SegmenterTests(unittest.TestCase):
    def test_phrase_boundaries(self):
        probabilities = [0.0] * 5 + [0.9] * 20 + [0.0] * 30
        vad = Mock(side_effect=probabilities)
        segmenter = Segmenter(vad, threshold=0.5, silence_ms=320, preroll_ms=96)
        events = [segmenter.push(np.ones(512, dtype=np.float32))[0] for _ in probabilities]
        self.assertEqual(events.count('start'), 1)
        self.assertEqual(events.count('end'), 1)

    def test_short_click_is_ignored(self):
        probabilities = [0.9] * 2 + [0.0] * 30
        segmenter = Segmenter(Mock(side_effect=probabilities), silence_ms=320, min_ms=250)
        events = [segmenter.push(np.ones(512, dtype=np.float32))[0] for _ in probabilities]
        self.assertNotIn('end', events)

    def test_energy_fallback(self):
        vad = StreamingVad(None)
        self.assertEqual(vad.engine, 'energy')
        quiet = [vad(np.random.uniform(-0.001, 0.001, 512).astype(np.float32)) for _ in range(20)]
        loud = vad(np.sin(np.arange(512) / 5).astype(np.float32) * 0.5)
        self.assertLess(max(quiet), 0.5)
        self.assertGreater(loud, 0.9)


class EngineChoiceTests(unittest.TestCase):
    def test_auto(self):
        self.assertEqual(choose_engine({'voice_language': 'auto'}, {'parakeet', 'gigaam'}), 'parakeet')
        self.assertEqual(choose_engine({'voice_language': 'ru'}, {'parakeet', 'gigaam'}), 'gigaam')
        self.assertEqual(choose_engine({'voice_language': 'ru'}, {'parakeet'}), 'parakeet')
        self.assertEqual(choose_engine({'voice_language': 'en'}, {'whisper'}), 'whisper')
        self.assertEqual(choose_engine({'stt_engine': 'whisper', 'voice_language': 'auto'}, {'parakeet', 'whisper'}), 'whisper')


class SpeakerTests(unittest.TestCase):
    def test_sentences_stream_to_tts(self):
        player = FakePlayer()
        speaker = SentenceSpeaker(player, {})
        for chunk in ['Курс доллара ', '81.5 рубля. За', 'втра будет ', 'дождь! Хорошего', ' дня']:
            speaker.feed(chunk)
        self.assertEqual(player.said, ['Курс доллара 81.5 рубля.', 'Завтра будет дождь!'])
        speaker.finish('...')
        self.assertEqual(player.said[-1], 'Хорошего дня')

    def test_whole_result_when_not_streamed(self):
        player = FakePlayer()
        SentenceSpeaker(player, {}).finish('Открываю калькулятор')
        self.assertEqual(player.said, ['Открываю калькулятор'])

    def test_readable(self):
        self.assertEqual(readable('**Итог**: см. https://example.com'), 'Итог : см. ссылку')


class ServiceTests(unittest.TestCase):
    def test_history_events_and_speech(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            agent = Mock()
            agent.process_command.side_effect = lambda text, settings, owner, on_text: (on_text('Привет. '), 'Привет.')[1]
            events = EventBus()
            player = FakePlayer()
            service = AssistantService(store, agent, events, player)
            stream = events.stream(heartbeat=0.05)
            next(stream)
            answer, spoken = service.run('Привет', 'device:desktop', store.settings('device:desktop'), source='voice')
            self.assertEqual((answer, spoken), ('Привет.', True))
            self.assertEqual(player.said, ['Привет.'])
            self.assertEqual([m['role'] for m in store.history('device:desktop')], ['user', 'agent'])
            kinds = [next(stream) for _ in range(5)]
            self.assertTrue(any('"delta"' in k for k in kinds))


if __name__ == '__main__':
    unittest.main()


class FakeMicrophone:
    """Тишина → фраза (синус) → тишина, кадрами по 512 отсчётов."""

    def __init__(self, device):
        self.level = 0.0
    def open(self):
        return self
    def close(self):
        pass
    def frames(self, stop_event):
        t = np.arange(512) / 16000
        noise = lambda: np.random.uniform(-0.0005, 0.0005, 512).astype(np.float32)
        for _ in range(30):
            yield noise()
        for _ in range(30):
            yield (np.sin(2 * np.pi * 220 * t) * 0.4).astype(np.float32)
        for _ in range(40):
            yield noise()
        stop_event.wait(2)


class PipelineTests(unittest.TestCase):
    def test_microphone_to_command(self):
        service = Mock()
        service.run.return_value = ('Привет!', True)
        values = {'wake_word': 'Андрей', 'voice_language': 'auto', 'silence_ms': 400, 'vad_sensitivity': 50,
                  'follow_up_seconds': 0, 'voice_enabled': True}
        voice = VoiceAssistant(FakeSpeech('Андрей, привет'), service, EventBus(), lambda: values,
                               player=FakePlayer(), microphone_factory=FakeMicrophone)
        voice.start()
        deadline = time.monotonic() + 5
        while not service.run.called and time.monotonic() < deadline:
            time.sleep(0.05)
        voice.stop()
        self.assertEqual(service.run.call_args.args[0], 'привет')
        self.assertEqual(voice.vad_engine, 'energy')
