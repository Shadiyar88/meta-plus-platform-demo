"""PostgreSQL persistence for the existing, server-authorized META+ application.

Private tables are never exposed to browser clients. The runtime role has DML
permissions only; schema installation is performed separately by the owner.
"""
import re
import sqlite3
from contextlib import contextmanager

IDENTITY_TABLES = {'users','groups','enrollments','slots','homework','assessments',
                   'invoices','payments','payment_claims','audit'}

class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)

def translate(sql):
    """Translate the small SQL dialect used by core.py, preserving literal '?'."""
    sql = sql.strip().rstrip(';')
    ignore = bool(re.match(r'INSERT\s+OR\s+IGNORE\s+', sql, re.I))
    if ignore:
        sql = re.sub(r'^INSERT\s+OR\s+IGNORE\s+', 'INSERT ', sql, flags=re.I)
        sql += ' ON CONFLICT DO NOTHING'
    # SQLite NOCASE username lookups; uniqueness uses a lower(username) index.
    sql = re.sub(r'\busername\s*=\s*\?', 'lower(username)=lower(?)', sql, flags=re.I)
    # Timestamps stay ISO text to preserve the existing API contract.
    sql = re.sub(r'\bCURRENT_TIMESTAMP\b',
                 "to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')", sql)
    out=[]; quote=None; i=0
    while i < len(sql):
        c=sql[i]
        if c in ("'", '"'):
            if quote == c:
                if i+1 < len(sql) and sql[i+1] == c:
                    out.extend((c,c)); i+=2; continue
                quote=None
            elif quote is None: quote=c
        if quote is None and c.isalpha():
            j=i+1
            while j<len(sql) and (sql[j].isalnum() or sql[j]=='_'): j+=1
            word=sql[i:j]
            out.append('"end"' if word.lower()=='end' else word)
            i=j; continue
        out.append('%s' if c=='?' and quote is None else '%%' if c=='%' else c)
        i+=1
    result=''.join(out)
    insert=re.match(r'INSERT\s+INTO\s+(\w+)\b', result, re.I)
    returns_id=bool(insert and insert.group(1).lower() in IDENTITY_TABLES)
    if returns_id: result+=' RETURNING id'
    return result, returns_id

class Cursor:
    def __init__(self, cursor, returns_id=False):
        self.cursor=cursor
        self.rowcount=cursor.rowcount
        self.lastrowid=None
        self.returning=returns_id
        if returns_id:
            row=cursor.fetchone()
            self.lastrowid=row[0] if row else None
    def fetchone(self):
        row=self.cursor.fetchone()
        if row is None: return None
        return Row(zip((c.name for c in self.cursor.description),row))
    def fetchall(self): return list(self)
    def __iter__(self):
        while True:
            row=self.fetchone()
            if row is None: break
            yield row

class Connection:
    def __init__(self, connection):
        self.connection=connection
        self.total_changes=0
        self.locked=False
    @property
    def in_transaction(self):
        # This reflects the write-lock semantics used by the original app.
        return self.locked
    def execute(self, sql, args=()):
        import psycopg
        if sql.strip().upper() == 'BEGIN IMMEDIATE':
            # Match SQLite's serialized mutations, including billing checks.
            # Acquired after authentication and released on commit/rollback.
            if not self.locked:
                cursor=self.connection.execute('SELECT pg_advisory_xact_lock(74261001)')
                self.locked=True
            else: cursor=self.connection.execute('SELECT 1')
            return Cursor(cursor)
        query, returns_id=translate(sql)
        try:
            cursor=self.connection.execute(query,tuple(args))
        except psycopg.IntegrityError as exc:
            raise sqlite3.IntegrityError('Database constraint violated') from exc
        if re.match(r'\s*(INSERT|UPDATE|DELETE)\b',query,re.I):
            self.total_changes+=max(cursor.rowcount,0)
        return Cursor(cursor,returns_id)
    def commit(self): self.connection.commit(); self.locked=False
    def rollback(self): self.connection.rollback(); self.locked=False
    def close(self): self.connection.close()

@contextmanager
def connect(url):
    try: import psycopg
    except ImportError:
        raise RuntimeError('Install PostgreSQL dependencies: python3 -m pip install -r requirements.txt') from None
    # Require encryption. prepare_threshold=None supports Supavisor pooling.
    raw=psycopg.connect(url,sslmode='require',connect_timeout=15,keepalives_idle=10,keepalives_interval=5,keepalives_count=3,tcp_user_timeout=30000,
                       prepare_threshold=None,application_name='META+ backend',
                       options='-c search_path=meta_private,pg_catalog -c statement_timeout=15000 -c lock_timeout=15000')
    db=Connection(raw)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally: db.close()
