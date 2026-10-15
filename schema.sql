PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE,
 name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','teacher','student','parent')),
 password TEXT NOT NULL, grade INTEGER CHECK(grade BETWEEN 5 AND 11),
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS parent_children (
 parent_id INTEGER REFERENCES users(id), student_id INTEGER REFERENCES users(id),
 PRIMARY KEY(parent_id,student_id)
);
CREATE TABLE IF NOT EXISTS sessions (
 token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), csrf TEXT NOT NULL,
 expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS rate_limits (key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS groups (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, subject TEXT NOT NULL,
 teacher_id INTEGER REFERENCES users(id), fee INTEGER NOT NULL DEFAULT 15000 CHECK(fee>=0),
 active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS enrollments (
 id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES users(id),
 group_id INTEGER NOT NULL REFERENCES groups(id), start_date TEXT NOT NULL,
 end_date TEXT, CHECK(end_date IS NULL OR end_date>=start_date)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_enrollment ON enrollments(student_id,group_id) WHERE end_date IS NULL;
CREATE TABLE IF NOT EXISTS slots (
 id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES groups(id),
 day INTEGER NOT NULL CHECK(day BETWEEN 1 AND 7), start TEXT NOT NULL, end TEXT NOT NULL,
 room INTEGER NOT NULL CHECK(room BETWEEN 1 AND 3), active INTEGER NOT NULL DEFAULT 1,
 CHECK(start<end)
);
CREATE TABLE IF NOT EXISTS attendance (
 slot_id INTEGER REFERENCES slots(id), student_id INTEGER REFERENCES users(id), date TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('present','absent','late','excused')),
 updated_by INTEGER NOT NULL REFERENCES users(id), PRIMARY KEY(slot_id,student_id,date)
);
CREATE TABLE IF NOT EXISTS homework (
 id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES groups(id), title TEXT NOT NULL,
 body TEXT NOT NULL, due_date TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS submissions (
 homework_id INTEGER REFERENCES homework(id), student_id INTEGER REFERENCES users(id),
 body TEXT NOT NULL, submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 mark REAL CHECK(mark BETWEEN 0 AND 100), feedback TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(homework_id,student_id)
);
CREATE TABLE IF NOT EXISTS assessments (
 id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES users(id),
 group_id INTEGER NOT NULL REFERENCES groups(id), date TEXT NOT NULL, kind TEXT NOT NULL,
 score REAL NOT NULL CHECK(score>=0), maximum REAL NOT NULL CHECK(maximum>0),
 note TEXT NOT NULL DEFAULT '', created_by INTEGER NOT NULL REFERENCES users(id), CHECK(score<=maximum),
 UNIQUE(student_id,group_id,date,kind)
);
CREATE TABLE IF NOT EXISTS invoices (
 id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES users(id),
 group_id INTEGER NOT NULL REFERENCES groups(id), month TEXT NOT NULL,
 amount INTEGER NOT NULL CHECK(amount>=0), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(student_id,group_id,month)
);
CREATE TABLE IF NOT EXISTS payments (
 id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id),
 amount INTEGER NOT NULL CHECK(amount>0), date TEXT NOT NULL, method TEXT NOT NULL,
 reference TEXT NOT NULL, recorded_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, reversed INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS one_payment_reference ON payments(invoice_id,reference) WHERE reversed=0;
CREATE TABLE IF NOT EXISTS payment_claims (
 id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id),
 reference TEXT NOT NULL, submitted_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, status TEXT NOT NULL DEFAULT 'pending'
 CHECK(status IN ('pending','reviewed','rejected'))
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),action TEXT NOT NULL,
 detail TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
PRAGMA user_version=1;
