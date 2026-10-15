from contextlib import closing
import argparse
import getpass
import os
import secrets
import sqlite3
from pathlib import Path
from config import load
load()
import core

parser=argparse.ArgumentParser(description='META+ database and administrator setup')
sub=parser.add_subparsers(dest='command',required=True)
p=sub.add_parser('init');p.add_argument('--username',default='admin');p.add_argument('--name',default='Администратор META+');p.add_argument('--generate-password',action='store_true')
p=sub.add_parser('backup');p.add_argument('destination')
args=parser.parse_args();core.initialize()
if args.command=='init':
    password=secrets.token_urlsafe(18) if args.generate_password else getpass.getpass('Initial password (minimum 10 characters): ')
    with core.connect() as db:
        if db.execute('SELECT 1 FROM users WHERE username=?',(args.username,)).fetchone(): raise SystemExit('This username already exists. No account was changed.')
        db.execute("INSERT INTO users(username,name,role,password) VALUES (?,?,'admin',?)",(args.username,args.name,core.hash_password(password)))
    if args.generate_password:
        access=core.ROOT/'initial-access.txt'
        access.write_text('META+ local administrator account\nUsername: '+args.username+'\nPassword: '+password+'\n\nChange this password in Settings after your first login. Keep this file private.\n',encoding='utf-8')
        os.chmod(access,0o600)
        print('Account created. Your private login details are in initial-access.txt.')
    else: print('Administrator account created.')
else:
    if os.environ.get('META_DATABASE_URL'):
        raise SystemExit('For Supabase backups, use pg_dump or the Supabase dashboard. SQLite backup cannot back up PostgreSQL.')
    destination=Path(args.destination)
    if destination.exists(): raise SystemExit('Destination exists; choose a new filename.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with core.connect() as source,closing(sqlite3.connect(destination)) as target: source.backup(target)
    print('Backup written to '+str(destination))
