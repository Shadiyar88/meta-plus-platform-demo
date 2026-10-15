"""HTTP protocol tests using an in-memory connection (no browser or network needed)."""
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_platform import DatabaseFixture
from server import Handler
from ai import answer

class FakeSocket:
    def __init__(self,request):self.input=io.BytesIO(request);self.output=bytearray()
    def makefile(self,*args):return self.input
    def sendall(self,data):self.output.extend(data)

class HTTPTests(DatabaseFixture):
    # Reuse isolated database fixtures.
    def request(self,method,path,payload=None,headers=None):
        body=json.dumps(payload).encode() if payload is not None else b''
        values={'Host':'meta.test','Content-Type':'application/json','Content-Length':str(len(body))}
        if method=='POST':values['Origin']='http://meta.test'
        values.update(headers or {})
        req=(method+' '+path+' HTTP/1.0\r\n'+''.join(k+': '+v+'\r\n' for k,v in values.items())+'\r\n').encode()+body
        sock=FakeSocket(req)
        with patch.object(Handler,'log_message'),patch.dict('os.environ',{'META_ORIGIN':'http://meta.test'}):
            Handler(sock,('127.0.0.1',12345),SimpleNamespace(server_name='meta.test',server_port=8766))
        head,body=bytes(sock.output).split(b'\r\n\r\n',1)
        lines=head.decode().split('\r\n');status=int(lines[0].split()[1]);response_headers={}
        for line in lines[1:]:
            key,value=line.split(': ',1);response_headers[key.lower()]=value
        return status,response_headers,body
    def sign_in(self,username='studenta'):
        status,headers,body=self.request('POST','/api/login',{'username':username,'password':'Test-only-password-123'})
        self.assertEqual(status,200)
        return {'Cookie':headers['set-cookie'].split(';')[0],'X-CSRF-Token':json.loads(body)['csrf']}
    def test_http_login_cookie_and_scoped_state(self):
        headers=self.sign_in();status,out,body=self.request('GET','/api/state',headers=headers)
        self.assertEqual(status,200);result=json.loads(body)
        self.assertEqual(result['user']['role'],'student');self.assertNotIn('password',result['user'])
        self.assertEqual({g['id'] for g in result['groups']},{self.g})
    def test_http_anonymous_access_rejected(self):
        status,_,_=self.request('GET','/api/state');self.assertEqual(status,401)
    def test_http_origin_and_csrf_rejected(self):
        status,_,_=self.request('POST','/api/login',{'username':'studenta','password':'Test-only-password-123'},{'Origin':'https://attacker.example'})
        self.assertEqual(status,403)
        headers=self.sign_in();headers['X-CSRF-Token']='wrong'
        status,_,_=self.request('POST','/api/homework',{},headers);self.assertEqual(status,403)
    def test_http_role_enforced_on_write(self):
        status,_,_=self.request('POST','/api/groups',{},self.sign_in());self.assertEqual(status,403)
    def test_http_private_files_not_served(self):
        status,_,_=self.request('GET','/initial-access.txt',headers=self.sign_in('testadmin'));self.assertEqual(status,404)
        status,_,_=self.request('GET','/data/meta.sqlite3',headers=self.sign_in('testadmin'));self.assertEqual(status,404)
        self.assertEqual(self.request('GET','/source-timetable.png',headers=self.sign_in())[0],403)
    def test_http_logout_invalidates_session(self):
        headers=self.sign_in();self.assertEqual(self.request('POST','/api/logout',{},headers)[0],200)
        self.assertEqual(self.request('GET','/api/state',headers=headers)[0],401)
    def test_http_static_assets_and_csp(self):
        for path in ['/','/app.js','/style.css','/kaspi-qr.png']:
            status,headers,body=self.request('GET',path);self.assertEqual(status,200);self.assertTrue(body)
            self.assertIn("script-src 'self'",headers['content-security-policy'])
    def test_http_payment_export_admin_only(self):
        self.assertEqual(self.request('GET','/api/export?kind=payments',headers=self.sign_in())[0],403)
    def test_ai_live_adapter_with_mocked_provider(self):
        import core
        captured=[]
        def fake_call(request,timeout):
            captured.append(json.loads(request.data))
            return io.BytesIO(json.dumps({'content':[{'type':'text','text':'Ответ META+'}]}).encode())
        with patch.dict('os.environ',{'ANTHROPIC_API_KEY':'test-key','ANTHROPIC_MODEL':'test-model'}),patch('ai.urllib.request.urlopen',side_effect=fake_call),core.connect() as db:
            result=answer(db,{'message':'Какой адрес?','language':'ru'})
        self.assertEqual(result['engine'],'claude');self.assertEqual(result['reply'],'Ответ META+')
        self.assertNotIn('studenta',captured[0]['system']);self.assertNotIn('password',captured[0]['system'].lower().replace('passwords',''))

