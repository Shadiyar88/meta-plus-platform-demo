import base64
import calendar
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from seed import seed_schedule

ROOT=Path(__file__).resolve().parent
DB_PATH=Path(os.environ.get('META_DB',ROOT/'data'/'meta.sqlite3'))

class Error(Exception):
    def __init__(self,message,status=400): self.message,self.status=message,status

def today(): return datetime.now(ZoneInfo('Asia/Almaty')).date()
def check(condition,message,status=400):
    if not condition: raise Error(message,status)
def text(value,maximum=5000,required=True):
    check(isinstance(value,str),'Ожидается текст.')
    value=value.strip()
    check(len(value)<=maximum and (bool(value) or not required),'Проверьте длину поля.')
    return value

def integer(value,low=1,high=100000000):
    check(isinstance(value,(int,str)) and not isinstance(value,bool),'Ожидается целое число.')
    try: result=int(value)
    except (ValueError,TypeError): raise Error('Ожидается целое число.')
    check(str(result)==str(value), 'Ожидается целое число.')
    check(low<=result<=high,'Число вне допустимого диапазона.')
    return result

def number(value,low=0,high=100000):
    check(not isinstance(value,bool),'Ожидается число.')
    try: result=float(value)
    except (ValueError,TypeError): raise Error('Ожидается число.')
    check(low<=result<=high,'Число вне допустимого диапазона.')
    return result

def iso_date(value):
    try: parsed=date.fromisoformat(value)
    except (ValueError,TypeError): raise Error('Проверьте дату.')
    check(parsed.isoformat()==value,'Проверьте дату.')
    return value

def month(value):
    check(isinstance(value,str) and bool(re.fullmatch(r'\d{4}-\d{2}',value)),'Проверьте месяц.')
    iso_date(value+'-01')
    return value

def clock(value):
    check(isinstance(value,str) and bool(re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value)),'Проверьте время.')
    return value

def password_text(password):
    check(isinstance(password,str) and 0<len(password)<=200,'Проверьте пароль.')
    return password

def hash_password(password):
    password=password_text(password)
    check(len(password)>=10,'Пароль должен содержать минимум 10 символов.')
    salt=secrets.token_bytes(16)
    key=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600000)
    return 'pbkdf2$600000$'+salt.hex()+'$'+key.hex()

def verify_password(password,encoded):
    try:
        _,iterations,salt,key=encoded.split('$')
        actual=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),int(iterations))
        return hmac.compare_digest(actual.hex(),key)
    except (ValueError,AttributeError,TypeError): return False

@contextmanager
def connect():
    url=os.environ.get('META_DATABASE_URL')
    if url:
        from postgres import connect as postgres_connect
        with postgres_connect(url) as db:
            yield db
        return
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DB_PATH,timeout=15)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally: db.close()

def initialize():
    if os.environ.get('META_DATABASE_URL'):
        with connect() as db:
            db.execute('SELECT 1 FROM users LIMIT 1')
            db.execute("SELECT 1 FROM settings WHERE key='monthly_fee'")
        return
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript((ROOT/'schema.sql').read_text(encoding='utf-8'))
        for k,v in {'kaspi_url':'','unt_anchor':'','address':'А.Яссауи даңғылы, 87Б, Кентау','monthly_fee':'15000'}.items():
            db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',(k,v))
        seed_schedule(db)


def rows(db,sql,args=()): return [dict(r) for r in db.execute(sql,args)]
def one(db,sql,args=(),message='Запись не найдена.'):
    r=db.execute(sql,args).fetchone()
    check(r is not None,message,404)
    return dict(r)
def audit(db,actor,action,detail):
    db.execute('INSERT INTO audit(user_id,action,detail) VALUES (?,?,?)',(actor,action,json.dumps(detail,ensure_ascii=False)))
def admin(user): check(user['role']=='admin','Только администратор.',403)
def group_access(db,user,gid,write=False):
    g=one(db,'SELECT * FROM groups WHERE id=?',(gid,))
    if user['role']=='admin': return g
    if user['role']=='teacher':
        check(g['teacher_id']==user['id'],'Это не ваша группа.',403)
        return g
    check(not write,'Изменение недоступно.',403)
    ids=student_ids(db,user)
    check(any(db.execute('SELECT 1 FROM enrollments WHERE group_id=? AND student_id=?',(gid,s)).fetchone() for s in ids),'Нет доступа к группе.',403)
    return g

def student_ids(db,user):
    if user['role']=='student': return [user['id']]
    if user['role']=='parent': return [r[0] for r in db.execute('SELECT student_id FROM parent_children WHERE parent_id=?',(user['id'],))]
    return []

def enrolled(db,sid,gid,on=None):
    if on:
        return bool(db.execute('SELECT 1 FROM enrollments WHERE student_id=? AND group_id=? AND start_date<=? AND (end_date IS NULL OR end_date>=?)',(sid,gid,on,on)).fetchone())
    return bool(db.execute('SELECT 1 FROM enrollments WHERE student_id=? AND group_id=? AND end_date IS NULL',(sid,gid)).fetchone())

def invoice_access(db,user,iid):
    invoice=one(db,'SELECT * FROM invoices WHERE id=?',(iid,))
    check(user['role']=='admin' or invoice['student_id'] in student_ids(db,user),'Нет доступа к платежам.',403)
    return invoice

def check_slot(db,slot,exclude=0):
    for other in rows(db,'''SELECT s.*,g.teacher_id FROM slots s JOIN groups g ON g.id=s.group_id
                         WHERE s.active=1 AND s.day=? AND s.id!=?''',(slot['day'],exclude)):
        if slot['start']>=other['end'] or other['start']>=slot['end']: continue
        check(other['room']!=slot['room'],'Кабинет уже занят в это время.',409)
        check(other['group_id']!=slot['group_id'],'У группы уже есть занятие в это время.',409)
        teacher=one(db,'SELECT teacher_id FROM groups WHERE id=?',(slot['group_id'],))['teacher_id']
        check(not teacher or teacher!=other['teacher_id'],'У преподавателя уже есть занятие в это время.',409)
        intersection=db.execute('''SELECT 1 FROM enrollments a JOIN enrollments b ON a.student_id=b.student_id
                   WHERE a.group_id=? AND b.group_id=? AND a.end_date IS NULL AND b.end_date IS NULL LIMIT 1''',(slot['group_id'],other['group_id'])).fetchone()
        check(not intersection,'У ученика уже есть занятие в это время.',409)

def rate_limit(db,key,maximum=8,window=900):
    if not db.in_transaction: db.execute('BEGIN IMMEDIATE')
    now=int(time.time())
    db.execute('DELETE FROM rate_limits WHERE expires<?',(now,))
    row=db.execute('SELECT * FROM rate_limits WHERE key=?',(key,)).fetchone()
    if not row:
        db.execute('INSERT INTO rate_limits VALUES (?,1,?)',(key,now+window))
        return True
    if row['count']>=maximum: return False
    db.execute('UPDATE rate_limits SET count=count+1 WHERE key=?',(key,))
    return True

def login(username,password,ip):
    username=text(username,80)
    password=password_text(password)
    with connect() as db:
        allowed=rate_limit(db,'login-ip:'+ip,100) and rate_limit(db,'login-user:'+username.lower(),8)
    check(allowed,'Слишком много попыток. Повторите через 15 минут.',429)
    with connect() as db:
        row=db.execute('SELECT * FROM users WHERE username=? AND active=1',(username,)).fetchone()
        # Perform comparable work even when the username is absent.
        encoded=row['password'] if row else 'pbkdf2$600000$'+'00'*16+'$'+'00'*32
        valid=verify_password(password,encoded)
        check(bool(row) and valid,'Неверное имя пользователя или пароль.',401)
        db.execute('DELETE FROM rate_limits WHERE key=?',('login-user:'+username.lower(),))
        token=secrets.token_urlsafe(32)
        csrf=secrets.token_urlsafe(24)
        db.execute('DELETE FROM sessions WHERE expires<?',(int(time.time()),))
        db.execute('INSERT INTO sessions VALUES (?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['id'],csrf,int(time.time())+12*3600))
        audit(db,row['id'],'login',{})
        return token,csrf,{'id':row['id'],'name':row['name'],'role':row['role'],'username':row['username']}

def authenticate(db,token):
    check(bool(token),'Войдите в систему.',401)
    row=db.execute('''SELECT u.*,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id
                     WHERE s.token=? AND s.expires>? AND u.active=1''',(hashlib.sha256(token.encode()).hexdigest(),int(time.time()))).fetchone()
    check(row is not None,'Сессия завершена. Войдите снова.',401)
    return dict(row)


def state(db,user):
    groups=rows(db,'SELECT g.*,u.name teacher_name FROM groups g LEFT JOIN users u ON u.id=g.teacher_id')
    all_enroll=rows(db,'SELECT * FROM enrollments')
    ids=student_ids(db,user)
    if user['role']=='teacher': groups=[g for g in groups if g['teacher_id']==user['id']]
    elif user['role']!='admin': groups=[g for g in groups if any(e['group_id']==g['id'] and e['student_id'] in ids for e in all_enroll)]
    gids={g['id'] for g in groups}
    enroll=[e for e in all_enroll if e['group_id'] in gids and (user['role'] in ('admin','teacher') or e['student_id'] in ids)]
    visible_students={e['student_id'] for e in enroll}|set(ids)
    users=rows(db,'SELECT id,username,name,role,grade,active FROM users')
    if user['role']!='admin': users=[u for u in users if u['id']==user['id'] or u['id'] in visible_students or any(g['teacher_id']==u['id'] for g in groups)]
    history_slots=[s for s in rows(db,'SELECT * FROM slots') if s['group_id'] in gids]
    active_gids=gids if user['role'] in ('admin','teacher') else {e['group_id'] for e in enroll if e['end_date'] is None and e['start_date']<=today().isoformat()}
    slots=[s for s in history_slots if s['active'] and s['group_id'] in active_gids]
    if user['role'] not in ('admin','teacher'):
        recorded_sids={a['slot_id'] for a in rows(db,'SELECT slot_id,student_id FROM attendance') if a['student_id'] in ids}
        history_slots=[s for s in history_slots if s['group_id'] in active_gids or s['id'] in recorded_sids]
    sids={s['id'] for s in rows(db,'SELECT id,group_id FROM slots') if s['group_id'] in gids}
    attendance=[a for a in rows(db,'SELECT * FROM attendance') if a['slot_id'] in sids and (user['role'] in ('admin','teacher') or a['student_id'] in ids)]
    homework=[h for h in rows(db,'SELECT * FROM homework ORDER BY due_date DESC') if h['group_id'] in gids]
    if user['role'] not in ('admin','teacher'):
        homework=[h for h in homework if any(e['group_id']==h['group_id'] and e['student_id'] in ids and ((e['end_date'] is None and e['start_date']<=today().isoformat()) or (e['end_date'] is not None and e['start_date']<=h['created_at'][:10]<=e['end_date'])) for e in enroll)]
    hids={h['id'] for h in homework}
    submissions=[s for s in rows(db,'SELECT * FROM submissions') if s['homework_id'] in hids and (user['role'] in ('admin','teacher') or s['student_id'] in ids)]
    assessments=[a for a in rows(db,'SELECT * FROM assessments ORDER BY date') if a['group_id'] in gids and (user['role'] in ('admin','teacher') or a['student_id'] in ids)]
    invoices=[]
    if user['role']!='teacher':
        invoices=rows(db,'''SELECT i.*,COALESCE((SELECT SUM(amount) FROM payments p WHERE p.invoice_id=i.id AND p.reversed=0),0) paid
                            FROM invoices i ORDER BY month DESC,id DESC''')
        if user['role']!='admin': invoices=[i for i in invoices if i['student_id'] in ids]
    iids={i['id'] for i in invoices}
    payments=[p for p in rows(db,'SELECT * FROM payments ORDER BY id DESC') if p['invoice_id'] in iids]
    claims=[p for p in rows(db,'SELECT * FROM payment_claims ORDER BY id DESC') if p['invoice_id'] in iids]
    settings={r['key']:r['value'] for r in db.execute('SELECT * FROM settings')}
    next_unt=None
    if settings['unt_anchor']:
        anchor=date.fromisoformat(settings['unt_anchor'])
        gap=max(0,(today()-anchor).days)
        next_unt=(anchor+timedelta(days=((gap+13)//14)*14)).isoformat()
    return {'user':{k:user[k] for k in ('id','name','username','role','grade')},'csrf':user['csrf'],
            'today':today().isoformat(),'groups':groups,'users':users,'enrollments':enroll,
            'enrollment_candidates':rows(db,"SELECT id,name,grade FROM users WHERE role='student' AND active=1 ORDER BY name") if user['role'] in ('admin','teacher') else [],
            'parent_children':rows(db,'SELECT * FROM parent_children') if user['role']=='admin' else [],
            'slots':slots,'history_slots':history_slots,'attendance':attendance,'homework':homework,'submissions':submissions,
            'assessments':assessments,'invoices':invoices,'payments':payments,'claims':claims,
            'settings':settings,'next_unt':next_unt,
            'ai_enabled':bool(os.environ.get('ANTHROPIC_API_KEY') and os.environ.get('ANTHROPIC_MODEL')),
            'audit':rows(db,'SELECT a.*,u.name FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 100') if user['role']=='admin' else []}


def mutate(db,user,action,p):
    uid=user['id']
    db.execute('BEGIN IMMEDIATE')
    if action=='users':
        admin(user)
        username=text(p.get('username'),80)
        check(bool(re.fullmatch(r'[A-Za-z0-9_.-]{3,80}',username)),'Логин: латинские буквы, цифры, точка, дефис; минимум 3 символа.')
        role=p.get('role');check(role in ('admin','teacher','student','parent'),'Проверьте роль.')
        grade=integer(p.get('grade'),5,11) if role=='student' else None
        cursor=db.execute('INSERT INTO users(username,name,role,password,grade) VALUES (?,?,?,?,?)',
                          (username,text(p.get('name'),150),role,hash_password(p.get('password')),grade))
        result={'id':cursor.lastrowid}
    elif action=='user_update':
        admin(user);target=one(db,'SELECT * FROM users WHERE id=?',(integer(p.get('id')),))
        active=integer(p.get('active',target['active']),0,1)
        if target['role']=='admin' and not active:
            check(db.execute("SELECT count(*) FROM users WHERE role='admin' AND active=1 AND id!=?",(target['id'],)).fetchone()[0]>0,'Нельзя отключить последнего администратора.')
        grade=integer(p.get('grade',target['grade']),5,11) if target['role']=='student' else None
        if active and not target['active']:
            check(bool(p.get('password')),'Для активации установите новый пароль.')
        db.execute('UPDATE users SET name=?,grade=?,active=? WHERE id=?',(text(p.get('name',target['name']),150),grade,active,target['id']))
        if p.get('password'): db.execute('UPDATE users SET password=? WHERE id=?',(hash_password(p['password']),target['id']))
        if p.get('password') or not active: db.execute('DELETE FROM sessions WHERE user_id=?',(target['id'],))
        result={}
    elif action=='password':
        check(verify_password(p.get('current',''),user['password']),'Текущий пароль неверен.',403)
        db.execute('UPDATE users SET password=? WHERE id=?',(hash_password(p.get('password')),uid))
        db.execute('DELETE FROM sessions WHERE user_id=?',(uid,));result={}
    elif action=='parent_link':
        admin(user);pid=integer(p.get('parent_id'));sid=integer(p.get('student_id'))
        check(one(db,'SELECT role FROM users WHERE id=?',(pid,))['role']=='parent','Выберите родителя.')
        check(one(db,'SELECT role FROM users WHERE id=?',(sid,))['role']=='student','Выберите ученика.')
        if p.get('remove'): db.execute('DELETE FROM parent_children WHERE parent_id=? AND student_id=?',(pid,sid))
        else: db.execute('INSERT OR IGNORE INTO parent_children VALUES (?,?)',(pid,sid))
        result={}
    elif action=='groups':
        admin(user);gid=integer(p['id']) if p.get('id') else None
        if gid: one(db,'SELECT id FROM groups WHERE id=?',(gid,))
        teacher=integer(p['teacher_id']) if p.get('teacher_id') else None
        if teacher: check(one(db,'SELECT role FROM users WHERE id=?',(teacher,))['role']=='teacher','Выберите преподавателя.')
        values=(text(p.get('name'),150),text(p.get('subject'),100),teacher,integer(p.get('fee',15000),0),integer(p.get('active',1),0,1))
        if gid: db.execute('UPDATE groups SET name=?,subject=?,teacher_id=?,fee=?,active=? WHERE id=?',values+(gid,))
        else: gid=db.execute('INSERT INTO groups(name,subject,teacher_id,fee,active) VALUES (?,?,?,?,?)',values).lastrowid
        if not values[4]: db.execute('UPDATE slots SET active=0 WHERE group_id=?',(gid,))
        # Revalidate every affected slot after a teacher/group change; rollback on conflict.
        for slot in rows(db,'SELECT * FROM slots WHERE group_id=? AND active=1',(gid,)): check_slot(db,slot,slot['id'])
        result={'id':gid}
    elif action=='enroll':
        gid=integer(p.get('group_id'));sid=integer(p.get('student_id'))
        g=group_access(db,user,gid,True)
        check(one(db,'SELECT role FROM users WHERE id=?',(sid,))['role']=='student','Выберите ученика.')
        if p.get('remove'):
            membership=one(db,'SELECT * FROM enrollments WHERE student_id=? AND group_id=? AND end_date IS NULL',(sid,gid),'Ученик не записан в эту группу.')
            end=iso_date(p.get('date',today().isoformat()))
            check(membership['start_date']<=end<=today().isoformat(),'Дата ухода должна быть между датой записи и сегодняшним днём.')
            db.execute('UPDATE enrollments SET end_date=? WHERE student_id=? AND group_id=? AND end_date IS NULL',(end,sid,gid))
        else:
            check(g['active'],'Группа неактивна.')
            check(one(db,'SELECT active FROM users WHERE id=?',(sid,))['active'],'Аккаунт ученика отключён.')
            start=iso_date(p.get('date',today().isoformat()))
            db.execute('INSERT INTO enrollments(student_id,group_id,start_date) VALUES (?,?,?)',(sid,gid,start))
            for slot in rows(db,'SELECT * FROM slots WHERE group_id=? AND active=1',(gid,)): check_slot(db,slot,slot['id'])
        result={}
    elif action=='slots':
        admin(user);slot_id=integer(p['id']) if p.get('id') else None
        old=one(db,'SELECT * FROM slots WHERE id=?',(slot_id,)) if slot_id else {}
        if p.get('remove'):
            check(slot_id is not None,'Выберите занятие.')
            db.execute('UPDATE slots SET active=0 WHERE id=?',(slot_id,));result={}
        else:
            candidate={**old,**p}
            candidate={k:integer(candidate.get(k),1,7 if k=='day' else 3 if k=='room' else 100000000) for k in ('group_id','day','room')}|{k:clock(candidate.get(k)) for k in ('start','end')}
            check(candidate['start']<candidate['end'],'Окончание должно быть позже начала.')
            check('07:00'<=candidate['start'] and candidate['end']<='20:00','Расписание доступно с 07:00 до 20:00.')
            check(group_access(db,user,candidate['group_id'],True)['active'],'Группа неактивна.')
            if slot_id and any(candidate[k]!=old[k] for k in candidate):
                if db.execute('SELECT 1 FROM attendance WHERE slot_id=? LIMIT 1',(slot_id,)).fetchone():
                    # Keep attendance attached to the immutable previous timetable entry.
                    db.execute('UPDATE slots SET active=0 WHERE id=?',(slot_id,))
                    slot_id=None
            check_slot(db,candidate,slot_id or 0)
            values=tuple(candidate[k] for k in ('group_id','day','start','end','room'))
            if slot_id: db.execute('UPDATE slots SET group_id=?,day=?,start=?,end=?,room=?,active=1 WHERE id=?',values+(slot_id,))
            else: slot_id=db.execute('INSERT INTO slots(group_id,day,start,end,room) VALUES (?,?,?,?,?)',values).lastrowid
            result={'id':slot_id}
    elif action=='attendance':
        slot=one(db,'SELECT * FROM slots WHERE id=?',(integer(p.get('slot_id')),))
        group_access(db,user,slot['group_id'],True)
        day=iso_date(p.get('date'));check(date.fromisoformat(day).isoweekday()==slot['day'],'Дата не соответствует дню занятия.')
        check(day<=today().isoformat(),'Нельзя отмечать посещаемость в будущем.')
        marks=p.get('marks');check(isinstance(marks,list) and len(marks)<=500,'Проверьте список учеников.')
        for mark in marks:
            sid=integer(mark.get('student_id'));status=mark.get('status')
            check(enrolled(db,sid,slot['group_id'],day),'Ученик не был записан в группу на эту дату.',403)
            check(status in ('present','absent','late','excused',''),'Проверьте статус.')
            if not status: db.execute('DELETE FROM attendance WHERE slot_id=? AND student_id=? AND date=?',(slot['id'],sid,day))
            else: db.execute('''INSERT INTO attendance VALUES (?,?,?,?,?) ON CONFLICT(slot_id,student_id,date)
                               DO UPDATE SET status=excluded.status,updated_by=excluded.updated_by''',(slot['id'],sid,day,status,uid))
        result={}
    elif action=='homework':
        gid=integer(p.get('group_id'));group_access(db,user,gid,True)
        result={'id':db.execute('INSERT INTO homework(group_id,title,body,due_date,created_by) VALUES (?,?,?,?,?)',(gid,text(p.get('title'),200),text(p.get('body')),iso_date(p.get('due_date')),uid)).lastrowid}
    elif action=='submit':
        check(user['role']=='student','Работу отправляет ученик.',403)
        hid=integer(p.get('homework_id'));h=one(db,'SELECT * FROM homework WHERE id=?',(hid,))
        check(enrolled(db,uid,h['group_id'],today().isoformat()),'Вы не записаны в эту группу.',403)
        check(db.execute('SELECT 1 FROM enrollments WHERE student_id=? AND group_id=? AND end_date IS NULL AND start_date<=?',(uid,h['group_id'],today().isoformat())).fetchone(),'Запись в группу завершена.',403)
        previous=db.execute('SELECT mark FROM submissions WHERE homework_id=? AND student_id=?',(hid,uid)).fetchone()
        check(not previous or previous['mark'] is None,'Работа уже оценена. Обратитесь к преподавателю.')
        db.execute('''INSERT INTO submissions(homework_id,student_id,body) VALUES (?,?,?)
                      ON CONFLICT(homework_id,student_id) DO UPDATE SET body=excluded.body,submitted_at=CURRENT_TIMESTAMP''',(hid,uid,text(p.get('body'))));result={}
    elif action=='grade_submission':
        hid=integer(p.get('homework_id'));sid=integer(p.get('student_id'))
        h=one(db,'SELECT * FROM homework WHERE id=?',(hid,));group_access(db,user,h['group_id'],True)
        one(db,'SELECT * FROM submissions WHERE homework_id=? AND student_id=?',(hid,sid))
        db.execute('UPDATE submissions SET mark=?,feedback=? WHERE homework_id=? AND student_id=?',(number(p.get('mark'),0,100),text(p.get('feedback',''),2000,False),hid,sid));result={}
    elif action=='assessment':
        gid=integer(p.get('group_id'));sid=integer(p.get('student_id'));group_access(db,user,gid,True)
        day=iso_date(p.get('date'));check(enrolled(db,sid,gid,day),'Ученик не записан в группу на эту дату.',403)
        score=number(p.get('score'));maximum=number(p.get('maximum'),0.01)
        check(score<=maximum,'Баллы превышают максимум.')
        kind=text(p.get('kind'),100)
        db.execute('''INSERT INTO assessments(student_id,group_id,date,kind,score,maximum,note,created_by) VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(student_id,group_id,date,kind) DO UPDATE SET score=excluded.score,maximum=excluded.maximum,note=excluded.note,created_by=excluded.created_by''',
                   (sid,gid,day,kind,score,maximum,text(p.get('note',''),2000,False),uid));result={}
    elif action=='unt_assessment':
        gid=integer(p.get('group_id'));sid=integer(p.get('student_id'));group_access(db,user,gid,True)
        day=iso_date(p.get('date'));check(enrolled(db,sid,gid,day),'Ученик не записан в группу на эту дату.',403)
        profile1=text(p.get('profile1_name'),70);profile2=text(p.get('profile2_name'),70)
        check(profile1.casefold()!=profile2.casefold(),'Выберите два разных профильных предмета.')
        specs=(
            ('unt:history','history_score',20),
            ('unt:reading','reading_score',10),
            ('unt:math_literacy','math_literacy_score',10),
            ('unt:profile1:'+profile1,'profile1_score',50),
            ('unt:profile2:'+profile2,'profile2_score',50),
        )
        scores=[]
        for kind,key,maximum in specs:
            score=number(p.get(key),0,maximum);scores.append((kind,score,maximum))
        note=text(p.get('note',''),2000,False)
        db.execute("DELETE FROM assessments WHERE student_id=? AND group_id=? AND date=? AND kind LIKE 'unt:profile%'",(sid,gid,day))
        for kind,score,maximum in (*scores,('unt:total',sum(score for _,score,_ in scores),140)):
            db.execute('''INSERT INTO assessments(student_id,group_id,date,kind,score,maximum,note,created_by) VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(student_id,group_id,date,kind) DO UPDATE SET score=excluded.score,maximum=excluded.maximum,note=excluded.note,created_by=excluded.created_by''',
                       (sid,gid,day,kind,score,maximum,note if kind=='unt:total' else '',uid))
        result={'total':sum(score for _,score,_ in scores)}
    elif action=='invoices':
        admin(user);m=month(p.get('month'));start=m+'-01';last=m+'-'+str(calendar.monthrange(int(m[:4]),int(m[5:]))[1])
        before=db.total_changes
        db.execute('''INSERT OR IGNORE INTO invoices(student_id,group_id,month,amount)
                 SELECT DISTINCT e.student_id,e.group_id,?,g.fee FROM enrollments e JOIN groups g ON g.id=e.group_id JOIN users u ON u.id=e.student_id
                 WHERE u.active=1 AND e.start_date<=? AND (e.end_date IS NULL OR e.end_date>=?) AND g.active=1''',(m,last,start))
        result={'created':db.total_changes-before}
    elif action=='payment':
        admin(user);iid=integer(p.get('invoice_id'));invoice=invoice_access(db,user,iid)
        paid=db.execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE invoice_id=? AND reversed=0',(iid,)).fetchone()[0]
        amount=integer(p.get('amount'));check(paid+amount<=invoice['amount'],'Сумма превышает остаток по счёту.',409)
        check(iso_date(p.get('date'))<=today().isoformat(),'Дата оплаты не может быть в будущем.')
        result={'id':db.execute('INSERT INTO payments(invoice_id,amount,date,method,reference,recorded_by) VALUES (?,?,?,?,?,?)',
                   (iid,amount,iso_date(p.get('date')),text(p.get('method'),100),text(p.get('reference'),500),uid)).lastrowid}
        db.execute("UPDATE payment_claims SET status='reviewed' WHERE invoice_id=? AND status='pending'",(iid,))
    elif action=='reverse_payment':
        admin(user);pid=integer(p.get('id'));one(db,'SELECT * FROM payments WHERE id=?',(pid,))
        reason=text(p.get('reason'),500);db.execute('UPDATE payments SET reversed=1 WHERE id=?',(pid,));result={'reason':reason}
    elif action=='payment_claim':
        check(user['role'] in ('student','parent'),'Только ученик или родитель.',403)
        iid=integer(p.get('invoice_id'));invoice_access(db,user,iid)
        check(not db.execute("SELECT 1 FROM payment_claims WHERE invoice_id=? AND status='pending'",(iid,)).fetchone(),'Заявка уже ожидает проверки.')
        db.execute('INSERT INTO payment_claims(invoice_id,reference,submitted_by) VALUES (?,?,?)',(iid,text(p.get('reference'),1000),uid));result={}
    elif action=='reject_claim':
        admin(user);cid=integer(p.get('id'));one(db,'SELECT id FROM payment_claims WHERE id=?',(cid,))
        db.execute("UPDATE payment_claims SET status='rejected' WHERE id=?",(cid,));result={}
    elif action=='settings':
        admin(user);url=text(p.get('kaspi_url',''),500,False)
        if url:
            parsed=urlparse(url)
            check(parsed.scheme=='https' and (parsed.hostname=='kaspi.kz' or (parsed.hostname or '').endswith('.kaspi.kz')) and not parsed.username and not parsed.password,'Нужна HTTPS-ссылка Kaspi вашего центра.')
        anchor=p.get('unt_anchor','')
        if anchor: iso_date(anchor)
        for k,v in {'kaspi_url':url,'unt_anchor':anchor,'address':text(p.get('address'),300)}.items():
            db.execute('UPDATE settings SET value=? WHERE key=?',(v,k))
        result={}
    else: raise Error('Действие не найдено.',404)
    # Passwords and submitted student work are never copied into the audit log.
    clean={k:v for k,v in p.items() if k not in ('password','current','body','marks')}
    audit(db,uid,action,clean)
    return result
