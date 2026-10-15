"""Run the existing business tests against PostgreSQL without retaining fixtures.

Explicit opt-in: PYTHONPATH=<driver location> python tests/check_postgres.py
Each test uses one transaction; each app operation gets its own savepoint.
No student records, invoices, or payments are committed by this script.
"""
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from config import load
load()
import core
import postgres
from test_platform import PlatformTests

class PostgreSQLTests(PlatformTests):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get('META_DATABASE_URL'):
            raise unittest.SkipTest('Configure META_DATABASE_URL to run PostgreSQL tests')
        cls.password=core.hash_password('Test-only-password-123')
    @classmethod
    def tearDownClass(cls): pass
    def setUp(self):
        import psycopg
        self.raw=psycopg.connect(os.environ['META_DATABASE_URL'],sslmode='require',
             connect_timeout=15,keepalives_idle=10,keepalives_interval=5,keepalives_count=3,tcp_user_timeout=30000,prepare_threshold=None,
             options='-c search_path=meta_private,pg_catalog -c statement_timeout=15000 -c lock_timeout=15000')
        self.db=postgres.Connection(self.raw)
        self.original_connect=core.connect
        self.addCleanup(self.cleanup_database)
        self.counter=0
        @contextmanager
        def isolated_connect():
            self.counter+=1
            name='operation_'+str(self.counter)
            locked=self.db.locked
            self.raw.execute('SAVEPOINT '+name)
            try:
                yield self.db
                self.raw.execute('RELEASE SAVEPOINT '+name)
            except Exception:
                self.raw.execute('ROLLBACK TO SAVEPOINT '+name)
                self.raw.execute('RELEASE SAVEPOINT '+name)
                self.db.locked=locked
                raise
        core.connect=isolated_connect
        with core.connect() as db:
            for username,role,grade in [('testadmin','admin',None),('teachera','teacher',None),('teacherb','teacher',None),('studenta','student',11),('studentb','student',10)]:
                db.execute('INSERT INTO users(username,name,role,grade,password) VALUES (?,?,?,?,?)',
                           (username,username,role,grade,self.password))
            self.people={r['username']:dict(r)|{'csrf':'test-csrf'} for r in db.execute("SELECT * FROM users WHERE username IN ('testadmin','teachera','teacherb','studenta','studentb')")}
        self.admin=self.people['testadmin'];self.ta=self.people['teachera'];self.tb=self.people['teacherb'];self.sa=self.people['studenta'];self.sb=self.people['studentb']
        self.g=self.op('groups',{'name':'Test group A','subject':'Математика','teacher_id':self.ta['id'],'fee':15000})['id']
        self.gb=self.op('groups',{'name':'Test group B','subject':'Физика','teacher_id':self.tb['id'],'fee':15000})['id']
        self.op('enroll',{'student_id':self.sa['id'],'group_id':self.g,'date':'2026-01-01'})
        self.op('enroll',{'student_id':self.sb['id'],'group_id':self.gb,'date':'2026-01-01'})
    def cleanup_database(self):
        core.connect=self.original_connect
        self.raw.rollback()
        self.raw.close()

if __name__=='__main__':
    unittest.main(defaultTest='PostgreSQLTests',verbosity=2)
