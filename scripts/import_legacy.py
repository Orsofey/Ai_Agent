"""Explicit one-time import. Never deletes old files or overwrites current profiles."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.storage import Store, DEFAULTS


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('old_data',help='Folder containing users.json/chats.json/settings.json')
    parser.add_argument('--guest-key',help='Old guest_... key to import into the desktop guest profile')
    args=parser.parse_args()
    folder=Path(args.old_data).resolve()
    def read(name):
        path=folder/name
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    users,chats,settings=read('users.json'),read('chats.json'),read('settings.json')
    if not (users or chats or settings):raise SystemExit('No legacy data found')
    guests=sorted(k for k in set(chats)|set(settings) if k.startswith('guest_'))
    if guests and not args.guest_key:
        print('Guest profiles are NOT merged automatically. Choose one with --guest-key:')
        print('\n'.join(guests))
    store=Store()
    marker='legacy:'+hashlib.sha256((str(folder)+'|'+str(args.guest_key)).encode()).hexdigest()
    if store.meta(marker):raise SystemExit('This import was already performed.')
    with store.connect() as db:
        # Database backup via SQLite API; consistent even in WAL mode.
        import sqlite3
        backup=sqlite3.connect(store.root/'before-legacy-import.sqlite3')
        db.backup(backup);backup.close()
        for name, row in users.items():
            db.execute('INSERT OR IGNORE INTO users VALUES (?,?,?)',(name,row.get('password',''),row.get('email','')))
        mapping={name:'user:'+name for name in users}
        if args.guest_key:
            if args.guest_key not in guests:raise ValueError('Unknown guest key')
            mapping[args.guest_key]='device:desktop'
        for old, new in mapping.items():
            if not db.execute('SELECT 1 FROM history WHERE owner=?',(new,)).fetchone():
                for row in chats.get(old,[]):
                    for role, field in [('user','user'),('agent','agent')]:
                        db.execute('INSERT INTO history(owner,role,text) VALUES (?,?,?)',(new,role,str(row.get(field,''))))
            if not db.execute('SELECT 1 FROM settings WHERE owner=?',(new,)).fetchone():
                value=dict(DEFAULTS)
                for k,v in settings.get(old,{}).items():
                    if k in DEFAULTS and type(v) is type(DEFAULTS[k]):value[k]=v
                value['voice_language']=value['voice_language'].split('-')[0]
                db.execute('INSERT INTO settings VALUES (?,?)',(new,json.dumps(value,ensure_ascii=False)))
        db.execute('INSERT INTO meta VALUES (?,?)',(marker,'1'))
    print('Import completed. Original JSON files were not changed.')


if __name__=='__main__':main()
