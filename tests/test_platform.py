from contextlib import closing
import hashlib
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core

class DatabaseFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.original=core.DB_PATH
        cls.base=Path(cls.tmp.name)/'base.sqlite';core.DB_PATH=cls.base;core.initialize()
        password=core.hash_password('Test-only-password-123')
        with core.connect() as db:
            for username,role,grade in [('testadmin','admin',None),('teachera','teacher',None),('teacherb','teacher',None),('studenta','student',11),('studentb','student',10)]:
                db.execute('INSERT INTO users(username,name,role,grade,password) VALUES (?,?,?,?,?)',(username,username,role,grade,password))
    @classmethod
    def tearDownClass(cls):core.DB_PATH=cls.original;cls.tmp.cleanup()
    def setUp(self):
        core.DB_PATH=Path(self.tmp.name)/'test.sqlite'
        if core.DB_PATH.exists():core.DB_PATH.unlink()
        with closing(sqlite3.connect(self.base)) as source,closing(sqlite3.connect(core.DB_PATH)) as target:source.backup(target)
        with core.connect() as db:
            self.people={r['username']:dict(r)|{'csrf':'test-csrf'} for r in db.execute("SELECT * FROM users WHERE username IN ('testadmin','teachera','teacherb','studenta','studentb')")}
        self.admin=self.people['testadmin'];self.ta=self.people['teachera'];self.tb=self.people['teacherb'];self.sa=self.people['studenta'];self.sb=self.people['studentb']
        self.g=self.op('groups',{'name':'Test group A','subject':'Математика','teacher_id':self.ta['id'],'fee':15000})['id']
        self.gb=self.op('groups',{'name':'Test group B','subject':'Физика','teacher_id':self.tb['id'],'fee':15000})['id']
        self.op('enroll',{'student_id':self.sa['id'],'group_id':self.g,'date':'2026-01-01'})
        self.op('enroll',{'student_id':self.sb['id'],'group_id':self.gb,'date':'2026-01-01'})
    def op(self,action,p,user=None):
        with core.connect() as db:return core.mutate(db,user or self.admin,action,p)
    def snapshot(self,user):
        with core.connect() as db:return core.state(db,user)
    def slot(self,gid=None,day=1,start='07:00',end='08:00',room=1):
        return self.op('slots',{'group_id':gid or self.g,'day':day,'start':start,'end':end,'room':room})['id']
    def invoice(self):
        self.op('invoices',{'month':'2026-09'})
        return next(i for i in self.snapshot(self.admin)['invoices'] if i['student_id']==self.sa['id'])
class PlatformTests(DatabaseFixture):
    def test_seed_has_three_rooms_and_named_teachers(self):
        state=self.snapshot(self.admin)
        self.assertEqual({s['room'] for s in state['slots']},{1,2,3})
        self.assertEqual(len([u for u in state['users'] if u['username'].startswith('teacher.')]),8)
        with core.connect() as db:
            for slot in core.rows(db,'SELECT * FROM slots WHERE active=1'):core.check_slot(db,slot,slot['id'])
    def test_login_and_session_revoke(self):
        token,csrf,user=core.login('studenta','Test-only-password-123','test')
        with core.connect() as db:actual=core.authenticate(db,token)
        self.assertEqual(actual['id'],self.sa['id']);self.assertTrue(csrf)
        self.op('password',{'current':'Test-only-password-123','password':'A-new-test-password-321'},actual)
        with core.connect() as db:
            with self.assertRaises(core.Error):core.authenticate(db,token)
    def test_wrong_and_disabled_logins(self):
        with self.assertRaises(core.Error):core.login('studenta','wrong-password','test')
        with self.assertRaises(core.Error):core.login('teacher.gulnaz','anything','test')
    def test_role_scoped_state(self):
        teacher=self.snapshot(self.ta);student=self.snapshot(self.sa)
        self.assertEqual({g['id'] for g in teacher['groups']},{self.g})
        self.assertEqual({g['id'] for g in student['groups']},{self.g})
        self.assertNotIn(self.sb['id'],{u['id'] for u in student['users']})
        self.invoice();self.assertEqual(self.snapshot(self.ta)['invoices'],[])
        self.assertEqual(len(self.snapshot(self.sa)['invoices']),1)
    def test_student_cannot_administer(self):
        for action,payload in [('users',{}),('groups',{}),('slots',{}),('invoices',{'month':'2026-09'}),('settings',{})]:
            with self.assertRaises(core.Error) as e:self.op(action,payload,self.sa)
            self.assertEqual(e.exception.status,403)
    def test_room_and_teacher_conflicts(self):
        sid=self.slot()
        with self.assertRaises(core.Error):self.slot(self.gb,start='07:30',end='08:30')
        self.op('groups',{'id':self.gb,'name':'Test group B','subject':'Физика','teacher_id':self.ta['id'],'fee':15000})
        with self.assertRaises(core.Error):self.slot(self.gb,room=2)
        self.assertTrue(sid)
    def test_student_conflict_rejects_enrollment_atomically(self):
        self.slot();self.slot(self.gb,room=2)
        with self.assertRaises(core.Error):self.op('enroll',{'group_id':self.gb,'student_id':self.sa['id'],'date':'2026-01-01'})
        with core.connect() as db:self.assertFalse(core.enrolled(db,self.sa['id'],self.gb))
    def test_add_move_and_remove_slot(self):
        sid=self.slot();self.op('slots',{'id':sid,'day':2,'room':3,'start':'07:00','end':'08:00'})
        slot=next(s for s in self.snapshot(self.admin)['slots'] if s['id']==sid);self.assertEqual(slot['day'],2)
        self.op('slots',{'id':sid,'remove':True});self.assertNotIn(sid,{s['id'] for s in self.snapshot(self.admin)['slots']})
    def test_attendance_permissions_and_persistence(self):
        sid=self.slot();d=core.today()
        while d.isoweekday()!=1:d-=core.timedelta(days=1)
        payload={'slot_id':sid,'date':d.isoformat(),'marks':[{'student_id':self.sa['id'],'status':'absent'}]}
        with self.assertRaises(core.Error):self.op('attendance',payload,self.tb)
        self.op('attendance',payload,self.ta)
        self.assertEqual(self.snapshot(self.sa)['attendance'][0]['status'],'absent')
        self.assertEqual(self.snapshot(self.sb)['attendance'],[])
        revision=self.op('slots',{'id':sid,'day':2})
        self.assertNotEqual(revision['id'],sid)
        self.assertEqual(self.snapshot(self.sa)['attendance'][0]['slot_id'],sid)
    def test_attendance_bulk_rolls_back_invalid_student(self):
        sid=self.slot();d=core.today()
        while d.isoweekday()!=1:d-=core.timedelta(days=1)
        with self.assertRaises(core.Error):self.op('attendance',{'slot_id':sid,'date':d.isoformat(),'marks':[{'student_id':self.sa['id'],'status':'present'},{'student_id':self.sb['id'],'status':'absent'}]},self.ta)
        self.assertEqual(self.snapshot(self.sa)['attendance'],[])
    def test_homework_submission_and_grading(self):
        hid=self.op('homework',{'group_id':self.g,'title':'Task','body':'Solve this','due_date':'2026-10-01'},self.ta)['id']
        with self.assertRaises(core.Error):self.op('submit',{'homework_id':hid,'body':'My answer'},self.sb)
        self.op('submit',{'homework_id':hid,'body':'My answer'},self.sa)
        self.op('grade_submission',{'homework_id':hid,'student_id':self.sa['id'],'mark':90,'feedback':'Good'},self.ta)
        self.assertEqual(self.snapshot(self.sa)['submissions'][0]['mark'],90)
        with self.assertRaises(core.Error):self.op('submit',{'homework_id':hid,'body':'Changed'},self.sa)
    def test_assessment_score_limits_and_privacy(self):
        payload={'group_id':self.g,'student_id':self.sa['id'],'date':'2026-09-01','kind':'ЕНТ','score':110,'maximum':140}
        self.op('assessment',payload,self.ta)
        self.assertEqual(self.snapshot(self.sa)['assessments'][0]['score'],110)
        self.assertEqual(self.snapshot(self.sb)['assessments'],[])
        with self.assertRaises(core.Error):self.op('assessment',{**payload,'score':150},self.ta)
    def test_unt_subject_scores_and_total_are_saved_atomically(self):
        payload={'group_id':self.g,'student_id':self.sa['id'],'date':'2026-09-02',
                 'history_score':16,'reading_score':8,'math_literacy_score':7,
                 'profile1_name':'Математика','profile1_score':42,
                 'profile2_name':'Физика','profile2_score':39,'note':'Practice UNT'}
        result=self.op('unt_assessment',payload,self.ta)
        records=[a for a in self.snapshot(self.sa)['assessments'] if a['date']=='2026-09-02']
        self.assertEqual(result['total'],112)
        self.assertEqual(len(records),6)
        total=next(a for a in records if a['kind']=='unt:total')
        self.assertEqual((total['score'],total['maximum'],total['note']),(112,140,'Practice UNT'))
        self.assertEqual({a['maximum'] for a in records if a['kind']!='unt:total'},{10,20,50})
        with self.assertRaises(core.Error):self.op('unt_assessment',{**payload,'profile2_name':'Математика'},self.ta)
        self.assertEqual(len([a for a in self.snapshot(self.sa)['assessments'] if a['date']=='2026-09-02']),6)
        with self.assertRaises(core.Error):self.op('unt_assessment',{**payload,'profile1_score':51},self.ta)
        self.op('unt_assessment',{**payload,'profile2_name':'Химия','profile2_score':40},self.ta)
        revised=[a for a in self.snapshot(self.sa)['assessments'] if a['date']=='2026-09-02']
        self.assertEqual(len(revised),6)
        self.assertEqual(next(a for a in revised if a['kind']=='unt:total')['score'],113)
        self.assertNotIn('unt:profile2:Физика',{a['kind'] for a in revised})
        with self.assertRaises(core.Error) as denied:self.op('unt_assessment',{**payload,'student_id':self.sb['id']},self.ta)
        self.assertEqual(denied.exception.status,403)
        with self.assertRaises(core.Error) as denied:self.op('unt_assessment',payload,self.sa)
        self.assertEqual(denied.exception.status,403)
    def test_biweekly_test_calendar(self):
        self.op('settings',{'address':'Кентау','kaspi_url':'','unt_anchor':(core.today()-core.timedelta(days=15)).isoformat()})
        self.assertEqual(self.snapshot(self.sa)['next_unt'],(core.today()+core.timedelta(days=13)).isoformat())
    def test_invoice_generation_idempotent_fee_snapshot(self):
        invoice=self.invoice();self.op('invoices',{'month':'2026-09'})
        self.assertEqual(len(self.snapshot(self.sa)['invoices']),1)
        self.op('groups',{'id':self.g,'name':'Test group A','subject':'Математика','teacher_id':self.ta['id'],'fee':16000})
        self.assertEqual(self.snapshot(self.sa)['invoices'][0]['amount'],15000)
    def test_claim_does_not_mark_paid_and_partial_payment(self):
        i=self.invoice();self.op('payment_claim',{'invoice_id':i['id'],'reference':'Kaspi receipt 123'},self.sa)
        self.assertEqual(self.snapshot(self.sa)['invoices'][0]['paid'],0)
        payment={'invoice_id':i['id'],'amount':5000,'date':'2026-09-01','method':'Kaspi','reference':'verified-123'}
        self.op('payment',payment);self.assertEqual(self.snapshot(self.sa)['invoices'][0]['paid'],5000)
        with self.assertRaises(core.Error):self.op('payment',{**payment,'amount':11000})
        self.assertEqual(self.snapshot(self.sa)['invoices'][0]['paid'],5000)
        pid=self.snapshot(self.sa)['payments'][0]['id'];self.op('reverse_payment',{'id':pid,'reason':'Entry error'})
        self.assertEqual(self.snapshot(self.sa)['invoices'][0]['paid'],0)
    def test_invoice_private_and_teacher_cannot_confirm(self):
        i=self.invoice()
        with self.assertRaises(core.Error):self.op('payment_claim',{'invoice_id':i['id'],'reference':'123'},self.sb)
        with self.assertRaises(core.Error):self.op('payment',{'invoice_id':i['id']},self.ta)
    def test_kaspi_url_validation(self):
        with self.assertRaises(core.Error):self.op('settings',{'address':'Кентау','kaspi_url':'https://kaspi.kz.attacker.example/pay','unt_anchor':''})
        self.op('settings',{'address':'Кентау','kaspi_url':'https://kaspi.kz/pay/example','unt_anchor':''})
    def test_last_admin_cannot_be_disabled(self):
        with self.assertRaises(core.Error):self.op('user_update',{'id':self.admin['id'],'active':0})
    def test_teacher_can_enroll_existing_student_in_own_group(self):
        self.op('enroll',{'group_id':self.g,'student_id':self.sb['id'],'date':'2026-09-01'},self.ta)
        self.assertIn(self.sb['id'],{e['student_id'] for e in self.snapshot(self.ta)['enrollments']})
        self.assertIn(self.g,{g['id'] for g in self.snapshot(self.sb)['groups']})
    def test_teacher_cannot_change_other_group_membership(self):
        for payload in [{'group_id':self.gb,'student_id':self.sa['id']}, {'group_id':self.gb,'student_id':self.sb['id'],'remove':True}]:
            with self.assertRaises(core.Error) as caught:self.op('enroll',payload,self.ta)
            self.assertEqual(caught.exception.status,403)
    def test_teacher_can_remove_own_student_preserving_account_and_invoice(self):
        self.invoice()
        self.op('enroll',{'group_id':self.g,'student_id':self.sa['id'],'remove':True,'date':core.today().isoformat()},self.ta)
        state=self.snapshot(self.sa)
        self.assertFalse(any(e['group_id']==self.g and e['end_date'] is None for e in state['enrollments']))
        self.assertEqual(len(state['invoices']),1)
        self.assertTrue(next(u for u in state['users'] if u['id']==self.sa['id'])['active'])
        with core.connect() as db:self.assertEqual(db.execute('SELECT end_date FROM enrollments WHERE student_id=? AND group_id=?',(self.sa['id'],self.g)).fetchone()[0],core.today().isoformat())
    def test_enrollment_directory_exposes_only_selection_fields(self):
        candidates=self.snapshot(self.ta)['enrollment_candidates']
        self.assertIn(self.sb['id'],{u['id'] for u in candidates})
        self.assertTrue(all(set(u)=={'id','name','grade'} for u in candidates))
        self.assertEqual(self.snapshot(self.sa)['enrollment_candidates'],[])
    def test_data_survives_new_database_connection(self):
        self.invoice()
        with core.connect() as db:self.assertEqual(db.execute('SELECT amount FROM invoices WHERE student_id=?',(self.sa['id'],)).fetchone()[0],15000)

if __name__=='__main__':unittest.main()
