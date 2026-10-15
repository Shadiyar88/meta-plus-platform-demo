# Supabase version

Start with [SUPABASE.md](SUPABASE.md). The instructions below describe the original local SQLite version.

# META+ — working education-center platform

Full frontend, Python backend, and persistent SQLite database. Open this folder in VS Code and run it. No Node.js, npm installation, or paid account is needed for the core platform.

## What is included

| Account | Access |
|---|---|
| Administrator | Users/password resets, teacher activation, groups, enrollments, all schedules, attendance, homework, results, invoices, verified payment ledger, and settings |
| Teacher | Their groups and timetable; adding/removing existing students in their own groups; attendance grid; homework creation and grading; student test results. No payment access. |
| Student / parent (shared login) | Their timetable, attendance, assignments, submissions, marks, test progress, invoices, and Kaspi QR |

Russian and Kazakh interface. The server checks permissions for reads and writes; selecting a page cannot change a user's role.

There are no fabricated students, attendance records, marks, or payments. The initial data consists of the latest timetable and eight teachers from the provided image. Teacher accounts start disabled with unknown random passwords. Set a new password and activate each before issuing access.

## Start in VS Code

1. Install Python 3.10 or newer from https://www.python.org/downloads/ if needed. This was checked with Python 3.14 on macOS. On Windows use `py` in place of `python3`; timezone support may require `py -m pip install tzdata`.
2. Open this `meta-plus-platform` folder in VS Code.
3. Open the VS Code terminal and run:

```sh
python3 manage.py init
python3 server.py
```

The first command creates username `admin` and asks you to choose a password (at least 10 characters). Password typing is hidden. Run `init` once, not on every restart. The second command starts the platform.

4. Open http://127.0.0.1:8766 and sign in.
5. Stop the server with Ctrl+C. Start it again with `python3 server.py`; your data remains.

If you are using the copy already running in this Codex workspace, an administrator was already created. Your generated local login is in **initial-access.txt**. Change the password in Settings after signing in. That private file and the database are excluded from the downloadable source archive and version control.

## First setup at META+

1. **Users:** edit each teacher, set a new password, and activate the account. Correct any spelling from the image. Create actual student accounts with their grades. Students and parents share the student login.
2. **Groups:** the timetable's original labels (such as `11/м1`) are retained. Rename them to clear course names when you provide the abbreviations. Teachers were linked from the timetable's color legend. Subject offerings now include informatics and both history courses shown in that newer image. Check every imported cell against the original image in Settings before using it with students.
3. **Groups → Members:** enroll a student with the date they joined. Remove them when they leave. Historical attendance and invoices remain.
4. **Timetable:** add lessons with group, weekday, start, end, and room 1–3. Edit by clicking a lesson. Drag a lesson to another cell to move it. Keyboard users can press Enter on a lesson to edit it. Conflicting rooms, teachers, groups, and students are rejected by the server. The timetable covers 07:00–20:00 and repeats weekly.
5. **Settings:** set the first real ENT/UNT practice-test date. The next date repeats every 14 days. This is a calendar reminder and score tracker; it does not provide exam questions or an online exam engine.
6. **Payments:** choose the month and click “Generate invoices / Выставить счета”. Repeating this does not create duplicates. Each enrolled course group is charged its monthly fee, initially 15,000 ₸. Invoices retain their amount if you later change the group's fee.

## Attendance and homework

- Attendance is an Excel-style grid: students in rows, actual lesson dates in columns. Choose the group and week. Each column shows the start time and room. Teachers can mark present, absent, late, or excused; blank clears a mark. Future dates cannot be marked.
- Saving attendance processes each column as a separate transaction. An invalid column rolls back; previously saved columns remain. A message explains partial completion if a later column fails.
- Moving a lesson that already has attendance preserves the old timetable entry and creates a new one. Removing a lesson also preserves records. Old marked lessons remain visible for their recorded weeks. Administrators can restore removed lessons if there is no conflict.
- Teachers create text-based homework and a due date. Students submit text or paste a link to their work. Teachers grade it out of 100 with feedback. Graded submissions cannot be overwritten by students.
- Results accept a test type, date, score, and maximum. The graph shows scores as percentages, while the table shows raw scores. Default maximum is editable; 140 is a starting field value, not an enforced exam rule.
- CSV downloads open in Excel; names and group labels are included. Actual `.xlsx` files and document/file uploads are not included.

## Kaspi payments

The provided **ИП МЕТА ПЛЮС** QR image is included on the payment page. Scan it in Kaspi and check the merchant and amount before paying. A student can submit the receipt number/date/amount as a payment claim. This does **not** change their paid balance.

Administrators check their Kaspi merchant transactions, then record the verified amount in the platform. Partial payments are supported. Overpayments and duplicate active receipt references against an invoice are rejected. Recording a payment marks pending claims for that invoice reviewed. Incorrect ledger entries can be reversed with a reason; the original entry remains in the audit trail. Reversal here changes the platform ledger, not money in Kaspi.

To add a clickable payment link, obtain your own merchant link from **Kaspi Pay → Remote payment / Удалённая оплата → Payment link / Ссылка для оплаты** and add it in Settings. The supplied QR photo was included as an image; a payment link was not extracted or verified.

Official instructions: https://guide.kaspi.kz/partner/ru/pos/payments/remote/q2019

A QR image or generic payment link does not give this app bank transaction access. Automatic Kaspi payment reconciliation is not implemented. It would require a verified merchant integration, credentials, and transaction matching; the platform never pretends a button click proves payment.

Billing currently charges a full month for any course enrollment overlapping that month. Discounts, prorating, refunds, and automatic recurring month generation are not implemented. Each group is a billable course; do not enroll the same student in multiple groups for the same course unless you intend separate invoices.

## Connect the real AI assistant

The server contains a real Claude Messages API adapter, including recent chat history and scoped timetable context. Without credentials the page clearly shows **center information**, not AI-generated responses.

1. Copy `.env.example` to `.env` in VS Code.
2. Enter your own Claude API key in `ANTHROPIC_API_KEY` and an available API model ID in `ANTHROPIC_MODEL`.
3. Restart the server.

Example configuration (replace the placeholders):

```dotenv
ANTHROPIC_API_KEY=your_own_api_key
ANTHROPIC_MODEL=an_available_model_id_from_your_account
```

Keys remain on the server. Questions and recent chat are sent to the provider when the user submits them. Grades, financial records, names, passwords, and student submissions are not supplied as model context. Timetable context follows the logged-in account's group access. The assistant cannot change records, confirm bookings, or verify payments. Each account is limited to 20 questions per 10 minutes. Provider failures show an error instead of a fabricated response.

The live API request was tested with a mocked provider. No real model request has been made because no API key/model was supplied. Provider usage can cost money. Official API reference: https://platform.claude.com/docs/en/api/overview

## Code map

```text
static/index.html      Frontend entry page
static/app.js          Login and all role-specific pages/forms
static/style.css       Responsive frontend styling
static/kaspi-qr.png     Your provided payment QR
static/source-timetable.png  Latest provided timetable (admin-only route)
server.py              HTTP server, sessions, CSRF checks, API routing, CSV export
core.py                Database access, permission checks, schedules and business logic
schema.sql             Database schema and constraints
seed.py                Transcribed timetable and disabled teacher accounts
ai.py                  Grounded Claude API adapter and explicit information mode
config.py              Non-executable .env loader
manage.py              Initial admin setup and database backups
tests/                 Database, permissions, and HTTP protocol tests
Dockerfile             Optional container build
compose.yaml           Optional persistent Docker service
```

Backend uses the Python standard library, SQLite, and cookie-based authentication. Frontend uses HTML, CSS, and JavaScript. Both are real source code; there is no frontend build step. The original JSX was used as a design reference rather than retained as an in-memory application.

## API

`GET /api/state` returns only records authorized for the session. `GET /api/export?kind=attendance|payments|assessments` returns scoped CSV (payment export is administrator-only).

JSON POST routes:

| Route | Permission / purpose |
|---|---|
| `/api/login`, `/api/logout`, `/api/password` | Sign-in, sign-out, own password change |
| `/api/users`, `/api/user_update` | Administrator creates/edits/disables accounts or resets passwords |
| `/api/groups`, `/api/enroll` | Administrator manages groups/memberships; assigned teachers may add/remove existing students in their own groups |
| `/api/slots` | Administrator adds, edits, moves, removes (`remove: true`), or restores a recurring lesson |
| `/api/attendance` | Administrator or assigned teacher saves marks for a lesson/date |
| `/api/homework`, `/api/grade_submission` | Administrator or assigned teacher creates tasks/grades submissions |
| `/api/submit` | Enrolled student submits their own work |
| `/api/assessment` | Administrator or assigned teacher records a student's result |
| `/api/invoices`, `/api/payment`, `/api/reverse_payment` | Administrator bills a month and records/corrects verified payments |
| `/api/payment_claim` | Student reports their own payment for administrator review |
| `/api/reject_claim`, `/api/settings` | Administrator reviews claims and updates center settings |
| `/api/ai` | Logged-in users ask the assistant |

Writes require the same-origin `Origin` header and the session's `X-CSRF-Token`, returned at login and in state. Sessions expire after 12 hours. Session tokens are stored hashed, cookies are HttpOnly/SameSite=Strict, passwords use salted PBKDF2-SHA256 (600,000 iterations), and login attempts are rate-limited. Password resets and account disabling invalidate sessions. SQL writes use transactions and foreign keys. Student input is escaped before rendering. Secrets and passwords are excluded from audit entries.

## Verification

```sh
python3 -m unittest discover -s tests -v
```

46 distinct backend and HTTP protocol checks cover account scoping, unauthorized writes, timetable conflicts, attendance rollback/history, homework, assessment ranges, billing idempotence, payment claims/partial payments/reversals, sessions, CSRF, and private-file access. HTTP checks use in-memory connections rather than a browser. JavaScript passed syntax checking. Visual browser verification was blocked by an unavailable browser security-policy check in Codex; browser layout and drag/drop must be manually verified before rollout.

## Backups

```sh
python3 manage.py backup backups/meta-backup.sqlite3
```

Choose a new destination filename each time. The command uses SQLite's consistent online backup API. Back up the database regularly and keep backups private. To restore, stop the app and restore a saved database to `data/meta.sqlite3` (preserve the existing database first). The payment QR is a source asset, not stored in the database.

## Public Docker deployment

Use [DEPLOYMENT.md](DEPLOYMENT.md) and `compose.production.yaml` for an HTTPS proxy, persistent database, and private backend network. The older local-only Docker compose example does not satisfy the public runtime guard. For local use, run `python3 server.py` directly.

The release refuses non-loopback binding without an exact HTTPS META_ORIGIN and secure cookies. Public deployment has not been executed because no hosting account or server was supplied.

## Make it available to META+ staff and families

The current server runs only on this computer. It is **not hosted online**. For real remote users, host it on an always-on server with a persistent database volume, an HTTPS reverse proxy, and backups. Set these environment values for your actual HTTPS domain:

```dotenv
META_ORIGIN=https://your-meta-domain.kz
META_SECURE_COOKIE=1
```

The backend can listen behind the proxy using `python3 server.py --host 0.0.0.0`; do not expose the plain HTTP backend directly. The included standard-library HTTP server is intended for local use and a modest deployment behind a hardened proxy; it has not undergone a production load/security review. Hosting, domain purchase, HTTPS setup, real user onboarding, live Kaspi reconciliation, WhatsApp integration, and email/password recovery are not completed by this source delivery.
