import hashlib
import os
import sqlite3
import unittest
from unittest.mock import patch
from test_platform import DatabaseFixture
import test_http as http_fixtures
import core
from server import Handler, validate_runtime

class ReleaseTests(DatabaseFixture):
    def test_future_enrollment_does_not_expose_timetable_or_homework(self):
        self.slot(self.gb)
        future=(core.today()+core.timedelta(days=30)).isoformat()
        self.op('enroll',{'group_id':self.gb,'student_id':self.sa['id'],'date':future})
        hid=self.op('homework',{'group_id':self.gb,'title':'Private upcoming task','body':'Task','due_date':future},self.tb)['id']
        state=self.snapshot(self.sa)
        self.assertNotIn(self.gb,{s['group_id'] for s in state['slots']})
        self.assertNotIn(self.gb,{s['group_id'] for s in state['history_slots']})
        self.assertNotIn(hid,{h['id'] for h in state['homework']})
        with self.assertRaises(core.Error):self.op('submit',{'homework_id':hid,'body':'Early submission'},self.sa)
    def test_removed_student_cannot_submit_or_see_new_schedule(self):
        hid=self.op('homework',{'group_id':self.g,'title':'Task','body':'Task','due_date':core.today().isoformat()},self.ta)['id']
        self.op('enroll',{'group_id':self.g,'student_id':self.sa['id'],'remove':True,'date':core.today().isoformat()},self.ta)
        self.slot()
        state=self.snapshot(self.sa)
        self.assertFalse(state['slots']);self.assertFalse(state['history_slots'])
        with self.assertRaises(core.Error):self.op('submit',{'homework_id':hid,'body':'Late after removal'},self.sa)
    def test_disabled_student_not_billed_for_new_month(self):
        self.op('user_update',{'id':self.sa['id'],'active':0})
        self.op('invoices',{'month':core.today().isoformat()[:7]})
        with core.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM invoices WHERE student_id=?',(self.sa['id'],)).fetchone()[0],0)
    def test_bad_removal_date_is_clear_and_rolls_back(self):
        with self.assertRaises(core.Error):self.op('enroll',{'group_id':self.g,'student_id':self.sa['id'],'remove':True,'date':'2025-01-01'},self.ta)
        with core.connect() as db:self.assertTrue(core.enrolled(db,self.sa['id'],self.g))
    def test_repeated_removal_reports_missing_enrollment(self):
        payload={'group_id':self.g,'student_id':self.sa['id'],'remove':True,'date':core.today().isoformat()}
        self.op('enroll',payload,self.ta)
        with self.assertRaises(core.Error) as caught:self.op('enroll',payload,self.ta)
        self.assertEqual(caught.exception.status,404)
    def test_password_whitespace_is_preserved(self):
        secret='  whitespace-password-123  '
        encoded=core.hash_password(secret)
        self.assertTrue(core.verify_password(secret,encoded))
        self.assertFalse(core.verify_password(secret.strip(),encoded))
        self.op('user_update',{'id':self.sa['id'],'password':secret})
        self.assertEqual(core.login('studenta',secret,'test-ip')[2]['id'],self.sa['id'])
    def test_successful_login_resets_account_failure_bucket(self):
        for _ in range(3):
            with self.assertRaises(core.Error):core.login('studenta','wrong-password','test-ip')
        core.login('studenta','Test-only-password-123','test-ip')
        with core.connect() as db:self.assertIsNone(db.execute('SELECT 1 FROM rate_limits WHERE key=?',('login-user:studenta',)).fetchone())
    def test_expired_session_rejected(self):
        token,_,_=core.login('studenta','Test-only-password-123','test-ip')
        with core.connect() as db:db.execute('UPDATE sessions SET expires=0')
        with core.connect() as db:
            with self.assertRaises(core.Error):core.authenticate(db,token)
    def test_boolean_score_is_rejected(self):
        with self.assertRaises(core.Error):core.number(True)
    def test_public_runtime_requires_https_and_secure_cookies(self):
        with patch.dict(os.environ,{'META_ORIGIN':'','META_SECURE_COOKIE':''}):
            with self.assertRaises(SystemExit):validate_runtime('0.0.0.0')
        with patch.dict(os.environ,{'META_ORIGIN':'https://meta.example','META_SECURE_COOKIE':'1'}):validate_runtime('0.0.0.0')
    def test_proxy_ip_requires_explicit_trust(self):
        handler=object.__new__(Handler);handler.client_address=('127.0.0.1',9000);handler.headers={'X-Forwarded-For':'203.0.113.44'}
        with patch.dict(os.environ,{'META_TRUSTED_PROXIES':''}):self.assertEqual(handler.client_ip(),'127.0.0.1')
        with patch.dict(os.environ,{'META_TRUSTED_PROXIES':'127.0.0.1/32'}):self.assertEqual(handler.client_ip(),'203.0.113.44')

class ReleaseHTTPTests(DatabaseFixture):
    request=http_fixtures.HTTPTests.request
    sign_in=http_fixtures.HTTPTests.sign_in
    def test_unrecognized_host_rejected(self):
        self.assertEqual(self.request('GET','/',headers={'Host':'attacker.example'})[0],403)
    def test_chunked_request_rejected(self):
        self.assertEqual(self.request('POST','/api/login',{'username':'studenta','password':'Test-only-password-123'},{'Transfer-Encoding':'chunked'})[0],400)
    def test_secure_cookie_is_enabled_for_https_configuration(self):
        with patch.dict(os.environ,{'META_SECURE_COOKIE':'1'}):
            status,headers,_=self.request('POST','/api/login',{'username':'studenta','password':'Test-only-password-123'})
        self.assertEqual(status,200);self.assertIn('; Secure',headers['set-cookie']);self.assertIn('HttpOnly',headers['set-cookie'])
