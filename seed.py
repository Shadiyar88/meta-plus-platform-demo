"""Fictional starter timetable for the public META+ portfolio demo.

This file intentionally contains no real students, teachers, passwords, payments,
or production data.
"""

import secrets


TEACHERS = [
    ("math", "Demo Mathematics Teacher"),
    ("physics", "Demo Physics Teacher"),
    ("biology", "Demo Biology Teacher"),
    ("chemistry", "Demo Chemistry Teacher"),
    ("history", "Demo History Teacher"),
    ("informatics", "Demo Informatics Teacher"),
]

# ISO weekday, room, start hour, group label, teacher key.
CELLS = [
    (1, 1, 10, "DEMO-MATH-A", "math"),
    (1, 2, 11, "DEMO-PHYSICS-A", "physics"),
    (2, 1, 10, "DEMO-BIOLOGY-A", "biology"),
    (2, 2, 11, "DEMO-CHEMISTRY-A", "chemistry"),
    (3, 1, 10, "DEMO-HISTORY-A", "history"),
    (3, 2, 11, "DEMO-IT-A", "informatics"),
    (4, 1, 10, "DEMO-MATH-B", "math"),
    (5, 2, 11, "DEMO-PHYSICS-B", "physics"),
]

SUBJECTS = {
    "math": "Mathematics",
    "physics": "Physics",
    "biology": "Biology",
    "chemistry": "Chemistry",
    "history": "History",
    "informatics": "Informatics",
}


def seed_schedule(db):
    """Create fictional teachers, groups, and lessons in an empty database."""
    if db.execute("SELECT count(*) FROM slots").fetchone()[0]:
        return

    from core import hash_password

    teachers = {}
    for key, name in TEACHERS:
        username = "demo.teacher." + key
        db.execute(
            "INSERT OR IGNORE INTO users(username,name,role,password,active) "
            "VALUES (?,?,'teacher',?,0)",
            (username, name, hash_password(secrets.token_urlsafe(24))),
        )
        teachers[key] = db.execute(
            "SELECT id FROM users WHERE username=?", (username,)
        ).fetchone()[0]

    for day, room, hour, label, key in CELLS:
        db.execute(
            "INSERT OR IGNORE INTO groups(name,subject,teacher_id) VALUES (?,?,?)",
            (label, SUBJECTS[key], teachers[key]),
        )
        group_id = db.execute(
            "SELECT id FROM groups WHERE name=?", (label,)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO slots(group_id,day,start,end,room) VALUES (?,?,?,?,?)",
            (group_id, day, f"{hour:02}:00", f"{hour + 1:02}:00", room),
        )
