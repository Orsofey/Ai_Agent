"""Экономия памяти: режимы, флаги llama-server (кеш 8 бит, один слот), запуск на старых сборках, выгрузка при простое."""
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.brain.local_llm import BINARY, LocalLLMServer, estimate_ram_mb, memory_profile
from test_local_llm import FAKE_SERVER

# «Старая сборка»: не знает флага -fa и сразу завершается с ошибкой.
OLD_BUILD = 'import sys\nif "-fa" in sys.argv: sys.exit(1)\n'


class ProfileTests(unittest.TestCase):
    def test_auto_by_ram(self):
        with patch('src.brain.local_llm.total_ram_gb', return_value=8.0):
            self.assertEqual(memory_profile({'memory_mode': 'auto'})['mode'], 'economy')
        with patch('src.brain.local_llm.total_ram_gb', return_value=16.0):
            self.assertEqual(memory_profile({})['mode'], 'balanced')
        self.assertEqual(memory_profile({'memory_mode': 'max'})['ctx'], 8192)

    def test_estimates_shrink(self):
        economy = estimate_ram_mb('qwen3-4b', {'memory_mode': 'economy'})
        balanced = estimate_ram_mb('qwen3-4b', {'memory_mode': 'balanced'})
        maximum = estimate_ram_mb('qwen3-4b', {'memory_mode': 'max'})
        self.assertLess(economy, balanced)
        self.assertLess(balanced, maximum)
        self.assertLess(estimate_ram_mb('qwen3-1.7b', {'memory_mode': 'economy'}), 1500)

    def test_setting_validated(self):
        from src.storage import Store
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            self.assertEqual(store.settings('u')['memory_mode'], 'auto')
            store.save_settings('u', {'memory_mode': 'economy'})
            with self.assertRaises(ValueError):
                store.save_settings('u', {'memory_mode': 'huge'})


@unittest.skipIf(sys.platform == 'win32', 'shell shim for the fake server is POSIX-only')
class ServerFlagsTests(unittest.TestCase):
    def make(self, prefix=''):
        root = Path(self.temp.name)
        runtime = root / 'models' / 'llama.cpp' / 'cpu'
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / 'fake_server.py').write_text(prefix + FAKE_SERVER)
        binary = runtime / BINARY
        binary.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{runtime / "fake_server.py"}" "$@"\n')
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
        model_dir = root / 'models' / 'llm' / 'qwen3-4b'
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / 'Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf').write_bytes(b'GGUF')
        return LocalLLMServer(root)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = None

    def tearDown(self):
        if self.server:
            self.server.stop()
        self.temp.cleanup()

    def test_balanced_flags(self):
        self.server = self.make()
        self.server.ensure({'memory_mode': 'balanced'}, wait=20)
        args = self.server.process.args
        self.assertEqual(args[args.index('-c') + 1], '4096')
        self.assertEqual(args[args.index('-np') + 1], '1')
        self.assertEqual(args[args.index('--cache-type-k') + 1], 'q8_0')
        self.assertIn('--cache-type-v', args)

    def test_economy_flags_and_restart_on_mode_change(self):
        self.server = self.make()
        self.server.ensure({'memory_mode': 'economy'}, wait=20)
        args = self.server.process.args
        self.assertEqual(args[args.index('-c') + 1], '2048')
        self.assertEqual(args[args.index('-ub') + 1], '256')
        first = self.server.process.pid
        self.server.ensure({'memory_mode': 'max'}, wait=20)
        self.assertNotEqual(self.server.process.pid, first)
        self.assertNotIn('--cache-type-k', self.server.process.args)  # максимум — полноточный кеш

    def test_old_build_retries_without_new_flags(self):
        self.server = self.make(OLD_BUILD)
        self.server.ensure({'memory_mode': 'balanced'}, wait=20)
        self.assertTrue(self.server.safe_mode)
        self.assertNotIn('-fa', self.server.process.args)
        self.assertTrue(self.server.healthy())

    def test_idle_unload_in_economy(self):
        self.server = self.make()
        self.server.ensure({'memory_mode': 'economy'}, wait=20)
        self.assertFalse(self.server.unload_if_idle())  # только что пользовались — не выгружаем
        self.server.last_used = time.monotonic() - 11 * 60
        self.assertTrue(self.server.unload_if_idle())
        self.assertFalse(self.server.running())
        self.server.ensure({'memory_mode': 'economy'}, wait=20)  # следующий вопрос запускает снова
        self.assertTrue(self.server.healthy())
        self.assertIn('llm_mb', self.server.memory({'memory_mode': 'economy'}))


if __name__ == '__main__':
    unittest.main()
