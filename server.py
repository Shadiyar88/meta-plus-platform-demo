import argparse
import csv
import hashlib
import io
import ipaddress
import threading
import logging
import json
import os
import sqlite3
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import parse_qs,urlparse
from config import load
load()
import core
from ai import answer

def validate_runtime(host):
    origin=os.environ.get('META_ORIGIN','')
    public=host not in ('127.0.0.1','localhost','::1')
    if public:
        parsed=urlparse(origin)
        if parsed.scheme!='https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise SystemExit('Public binding requires META_ORIGIN=https://your-domain (no path).')
        if os.environ.get('META_SECURE_COOKIE')!='1':
            raise SystemExit('Public binding requires META_SECURE_COOKIE=1 and an HTTPS proxy.')
    if os.environ.get('META_SECURE_COOKIE')=='1' and urlparse(origin).scheme!='https':
        raise SystemExit('Secure cookies require an HTTPS META_ORIGIN.')

class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,*args,**kwargs):
        self.capacity=threading.BoundedSemaphore(32)
        super().__init__(*args,**kwargs)
    def process_request(self,request,address):
        if not self.capacity.acquire(blocking=False):
            request.close();return
        try:super().process_request(request,address)
        except Exception:
            self.capacity.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.capacity.release()
    def get_request(self):
        request,address=super().get_request()
        request.settimeout(15)
        return request,address

MAX_BODY=65000
STATIC={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/kaspi-qr.png':'kaspi-qr.png','/source-timetable.png':'source-timetable.png'}

class Handler(BaseHTTPRequestHandler):
    server_version='META+'
    def headers_out(self,status,mime,body,cookie=None,filename=None):
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if cookie: self.send_header('Set-Cookie',cookie)
        if filename: self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)
    def json_out(self,status,result,cookie=None):
        self.headers_out(status,'application/json; charset=utf-8',json.dumps(result,ensure_ascii=False).encode(),cookie)
    def token(self):
        cookies=SimpleCookie()
        try: cookies.load(self.headers.get('Cookie',''))
        except Exception: return ''
        return cookies['meta_session'].value if 'meta_session' in cookies else ''
    def cookie(self,token='',clear=False):
        secure='; Secure' if os.environ.get('META_SECURE_COOKIE')=='1' else ''
        return f'meta_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if clear else 43200}'+secure
    def host_check(self):
        expected=urlparse(os.environ.get('META_ORIGIN','')).netloc
        host=self.headers.get('Host','').lower()
        port=self.server.server_port
        allowed={expected.lower()} if expected else {f'127.0.0.1:{port}',f'localhost:{port}',f'[::1]:{port}'}
        core.check(host in allowed,'Недопустимый адрес сервера.',403)
    def client_ip(self):
        peer=self.client_address[0]
        networks=os.environ.get('META_TRUSTED_PROXIES','').split(',')
        try:
            trusted=any(ipaddress.ip_address(peer) in ipaddress.ip_network(n.strip()) for n in networks if n.strip())
            if trusted:
                return str(ipaddress.ip_address(self.headers.get('X-Forwarded-For','').split(',')[-1].strip()))
        except ValueError:pass
        return peer
    def origin_check(self):
        expected=os.environ.get('META_ORIGIN','http://'+self.headers.get('Host',''))
        origin=self.headers.get('Origin')
        core.check(origin==expected,'Запрос должен исходить со страницы платформы.',403)
    def do_GET(self):
        try:
            parsed=urlparse(self.path)
            if parsed.path=='/api/health':
                with core.connect() as db:db.execute('SELECT id FROM users LIMIT 1').fetchone()
                self.json_out(200,{'status':'ok'});return
            self.host_check()
            if parsed.path in STATIC:
                if parsed.path=='/source-timetable.png':
                    with core.connect() as db:core.admin(core.authenticate(db,self.token()))
                name=STATIC[parsed.path];mime={'html':'text/html','js':'text/javascript','css':'text/css','png':'image/png'}[name.rsplit('.',1)[-1]]
                self.headers_out(200,mime+('' if name.endswith('.png') else '; charset=utf-8'),(core.ROOT/'static'/name).read_bytes());return
            with core.connect() as db:
                user=core.authenticate(db,self.token())
                if parsed.path=='/api/state': self.json_out(200,core.state(db,user));return
                if parsed.path=='/api/export':
                    kind=parse_qs(parsed.query).get('kind',['attendance'])[0]
                    core.check(kind in ('attendance','payments','assessments'),'Неизвестный отчёт.')
                    if kind=='payments': core.admin(user)
                    state=core.state(db,user);records=state[kind]
                    names={u['id']:u['name'] for u in state['users']}
                    groups={g['id']:g['name'] for g in state['groups']}
                    slots={s['id']:s for s in state['history_slots']}
                    invoices={i['id']:i for i in state['invoices']}
                    enriched=[]
                    for record in records:
                        if kind=='payments':
                            invoice=invoices[record['invoice_id']]
                            record={**record,'student':names.get(invoice['student_id'],''),'group':groups.get(invoice['group_id'],''),'month':invoice['month']}
                        elif kind=='attendance':
                            slot=slots[record['slot_id']]
                            record={**record,'student':names.get(record['student_id'],''),'group':groups.get(slot['group_id'],''),'start':slot['start'],'room':slot['room']}
                        else:record={**record,'student':names.get(record['student_id'],''),'group':groups.get(record['group_id'],'')}
                        enriched.append(record)
                    records=enriched
                    out=io.StringIO();out.write('\ufeff')
                    if records:
                        writer=csv.DictWriter(out,fieldnames=list(records[0]),delimiter=';');writer.writeheader()
                        for record in records:
                            safe={k:("'"+v if isinstance(v,str) and v.lstrip()[:1] in ('=','+','-','@') else v) for k,v in record.items()}
                            writer.writerow(safe)
                    else: out.write('No records\n')
                    self.headers_out(200,'text/csv; charset=utf-8',out.getvalue().encode(),filename=kind+'.csv');return
            raise core.Error('Страница не найдена.',404)
        except core.Error as exc: self.json_out(exc.status,{'error':exc.message})
        except Exception:
            logging.exception('Internal read error');self.json_out(500,{'error':'Ошибка сервера.'})
    def do_POST(self):
        try:
            self.host_check()
            self.origin_check()
            core.check(not self.headers.get('Transfer-Encoding'),'Chunked requests are not supported.',400)
            core.check(len(self.headers.get_all('Content-Length',[]))==1,'Нужен один заголовок Content-Length.',400)
            core.check(self.headers.get('Content-Type','').split(';')[0]=='application/json','Нужен JSON.',415)
            try: size=int(self.headers.get('Content-Length','0'))
            except ValueError: raise core.Error('Проверьте размер запроса.')
            core.check(0<size<=MAX_BODY,'Запрос слишком большой.',413)
            try: payload=json.loads(self.rfile.read(size))
            except (ValueError,UnicodeError): raise core.Error('Неверный JSON.')
            core.check(isinstance(payload,dict),'Ожидается объект JSON.')
            if self.path=='/api/login':
                token,csrf,user=core.login(payload.get('username'),payload.get('password'),self.client_ip())
                self.json_out(200,{'user':user,'csrf':csrf},self.cookie(token));return
            with core.connect() as db:
                user=core.authenticate(db,self.token())
                core.check(self.headers.get('X-CSRF-Token')==user['csrf'],'Обновите страницу и повторите запрос.',403)
                if self.path=='/api/logout':
                    db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(self.token().encode()).hexdigest(),))
                    result={}
                elif self.path=='/api/ai':
                    allowed=core.rate_limit(db,'ai:'+str(user['id']),20,600)
                    db.commit()
                    core.check(allowed,'Лимит: 20 вопросов за 10 минут.',429)
                    result=answer(db,payload,user)
                else:
                    core.check(self.path.startswith('/api/'),'Страница не найдена.',404)
                    result=core.mutate(db,user,self.path.removeprefix('/api/'),payload)
            self.json_out(200,result,self.cookie(clear=True) if self.path=='/api/logout' else None)
        except core.Error as exc: self.json_out(exc.status,{'error':exc.message})
        except sqlite3.IntegrityError:
            self.json_out(409,{'error':'Такая запись уже существует либо данные связаны с другими записями. Проверьте логин, название и даты.'})
        except (TypeError,AttributeError,KeyError): self.json_out(400,{'error':'Проверьте заполнение полей.'})
        except Exception:
            logging.exception('Internal write error');self.json_out(500,{'error':'Ошибка сервера. Изменения не сохранены.'})

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8766)
    args=parser.parse_args();validate_runtime(args.host)
    if not all((core.ROOT/'static'/name).is_file() for name in STATIC.values()):raise SystemExit('Missing frontend files. Run from the complete extracted project; do not move it while running.')
    core.initialize()
    with core.connect() as db:
        if not db.execute("SELECT 1 FROM users WHERE role='admin' AND active=1").fetchone():
            raise SystemExit('Сначала создайте администратора: python3 manage.py init')
    try:server=BoundedHTTPServer((args.host,args.port),Handler)
    except OSError as exc:
        raise SystemExit(f'Cannot start server: {exc}. Stop the other META+ server or use --port 8767.')
    print(f'META+ platform: http://{args.host}:{args.port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: server.server_close()
