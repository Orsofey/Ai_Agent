import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from src.storage import Store
from src.passwords import matches


class MigrationTests(unittest.TestCase):
    def test_legacy_password(self):
        salt='a'*32
        digest=hashlib.pbkdf2_hmac('sha256',b'password',salt.encode(),120000).hex()
        self.assertTrue(matches(salt+'$'+digest,'password'))
        self.assertFalse(matches(salt+'$'+digest,'wrong'))

    def test_import_and_no_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);old=root/'old';old.mkdir();new=root/'new'
            (old/'users.json').write_text('{}')
            (old/'chats.json').write_text(json.dumps({'guest_demo':[{'user':'hello','agent':'world'}]}))
            (old/'settings.json').write_text(json.dumps({'guest_demo':{'theme':'light','voice_language':'ru-RU'}}))
            env=dict(os.environ,LOCAL_AI_DATA_DIR=str(new))
            script=Path(__file__).resolve().parents[1]/'scripts/import_legacy.py'
            args=[sys.executable,str(script),str(old),'--guest-key','guest_demo']
            result=subprocess.run(args,env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            store=Store(new)
            self.assertEqual(len(store.history('device:desktop')),2)
            self.assertEqual(store.settings('device:desktop')['voice_language'],'ru')
            again=subprocess.run(args,env=env,capture_output=True,text=True,timeout=15)
            self.assertNotEqual(again.returncode,0)
            self.assertEqual(len(store.history('device:desktop')),2)
            self.assertTrue((old/'chats.json').exists())


if __name__=='__main__':unittest.main()
