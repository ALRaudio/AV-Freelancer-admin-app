import os, locale, json, sqlite3, calendar
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from functools import wraps

APP_NAME = os.getenv("APP_NAME","Freelancer Admin App")
SECRET_KEY = os.getenv("SECRET_KEY","change-me-please")
DEFAULT_VAT_PERCENT = int(os.getenv("DEFAULT_VAT_PERCENT","25"))
TIMEZONE = os.getenv("APP_TIMEZONE","Europe/Stockholm")

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///freelancer.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = SECRET_KEY

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
config_dir = os.path.join(APP_ROOT, "config")
data_dir = os.path.join(APP_ROOT, "data")
os.makedirs(data_dir, exist_ok=True)


db = SQLAlchemy(app)

# Absolute path for SQLite file used by ensure_schema
db_path = os.path.join(app.root_path, 'freelancer.sqlite3')



try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    from google.auth.transport.requests import Request
except Exception:
    Credentials = None
    Flow = None
    build = None
    Request = None


try:
    locale.setlocale(locale.LC_TIME, 'en_US.UTF-8')
except Exception:
    pass

def today_str():
    now = datetime.now()
    day = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][now.weekday()]
    month = ['','January','February','March','April','May','June','July','August','September','October','November','December'][now.month]
    return f"{day} {now.day:02d} {month} {now.year}"


def days_inclusive(start_dt, end_dt):
    start_date = start_dt.date()
    end_date = end_dt.date()
    return max(0, (end_date - start_date).days + 1)

def weeks_ceiling(start_dt, end_dt):
    d = days_inclusive(start_dt, end_dt)
    import math
    return 0 if d == 0 else math.ceil(d/7)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_logo_url = db.Column(db.String(500), nullable=True)
    favicon_url = db.Column(db.String(800), nullable=True)
    night_start_hour = db.Column(db.Integer, default=0)
    night_end_hour = db.Column(db.Integer, default=8)
    google_calendar_embed_url = db.Column(db.String(800), nullable=True)
    net_rate_percent = db.Column(db.Float, default=70.0)
    login_enabled = db.Column(db.Boolean, default=False)
    login_password = db.Column(db.String(200), nullable=True)
    gcal_enabled = db.Column(db.Boolean, default=False)
    gcal_calendar_id = db.Column(db.String(400), nullable=True)
    currency_code = db.Column(db.String(8), default='SEK')

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    default_vat_percent = db.Column(db.Integer, default=DEFAULT_VAT_PERCENT)
    logo_url = db.Column(db.String(500), nullable=True)
    roles = db.relationship("Role", backref="client", lazy=True)

class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    mode = db.Column(db.String(20), nullable=False) # 'hourly'|'production'|'daily'|'weekly'
    rate_sek = db.Column(db.Float, nullable=False)
    vat_percent = db.Column(db.Integer, default=DEFAULT_VAT_PERCENT)
    active = db.Column(db.Boolean, default=True)



def days_inclusive(start_dt, end_dt):
    start_date = start_dt.date()
    end_date = end_dt.date()
    return max(0, (end_date - start_date).days + 1)

def weeks_ceiling(start_dt, end_dt):
    d = days_inclusive(start_dt, end_dt)
    import math
    return 0 if d == 0 else math.ceil(d/7)

class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), nullable=False)
    start_dt = db.Column(db.DateTime, nullable=False)
    end_dt = db.Column(db.DateTime, nullable=False)
    vat_percent = db.Column(db.Integer, default=DEFAULT_VAT_PERCENT)
    detail = db.Column(db.String(200), nullable=True)
    gcal_event_id = db.Column(db.String(256), nullable=True)
    client = db.relationship("Client", lazy=True)
    role = db.relationship("Role", lazy=True)
    @property
    def duration_hours(self):
        h = (self.end_dt - self.start_dt).total_seconds()/3600.0
        return max(0.0, h)
    @property
    def amount_sek(self):
        if not self.role: return 0.0
        m = self.role.mode
        if m == 'hourly':
            return self.role.rate_sek * self.duration_hours
        elif m == 'production':
            return self.role.rate_sek
        elif m == 'daily':
            return self.role.rate_sek * days_inclusive(self.start_dt, self.end_dt)
        elif m == 'weekly':
            return self.role.rate_sek * weeks_ceiling(self.start_dt, self.end_dt)
        else:
            return self.role.rate_sek

class InvoiceStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    sent = db.Column(db.Boolean, default=False)
    paid = db.Column(db.Boolean, default=False)
    invoice_number = db.Column(db.String(120), nullable=True)
    client = db.relationship("Client", lazy=True)

class Holiday(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    surcharge_text = db.Column(db.String(120), nullable=True)


# ---------- Auto-migration ----------
def column_exists(cur, table, column):
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())

def ensure_schema():
    # Resolve DB path defensively
    path = globals().get('db_path') or os.path.join(app.root_path, 'freelancer.sqlite3')
    con = sqlite3.connect(path)
    cur = con.cursor()
    try:
        cur.execute("PRAGMA foreign_keys=ON")
        for (table, col, ddl) in [
            ('settings','gcal_enabled',"ALTER TABLE settings ADD COLUMN gcal_enabled BOOLEAN DEFAULT 0"),
            ('settings','gcal_calendar_id',"ALTER TABLE settings ADD COLUMN gcal_calendar_id VARCHAR(400)"),
            ('invoice_status','invoice_number',"ALTER TABLE invoice_status ADD COLUMN invoice_number VARCHAR(120)"),
            ('role','vat_percent',"ALTER TABLE role ADD COLUMN vat_percent INTEGER DEFAULT %d" % DEFAULT_VAT_PERCENT),
            ('settings','favicon_url',"ALTER TABLE settings ADD COLUMN favicon_url VARCHAR(800)"),
            ('settings','currency_code',"ALTER TABLE settings ADD COLUMN currency_code VARCHAR(8) DEFAULT 'SEK'"),
        ]:
            try:
                if not column_exists(cur, table, col):
                    cur.execute(ddl)
            except sqlite3.OperationalError:
                pass
        con.commit()
    finally:
        con.close()


# ---------- Auto-migration ----------
def column_exists(cur, table, column):
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())

def ensure_schema():
    # Resolve DB path defensively
    path = globals().get('db_path') or os.path.join(app.root_path, 'freelancer.sqlite3')
    con = sqlite3.connect(path)
    cur = con.cursor()
    try:
        cur.execute("PRAGMA foreign_keys=ON")
        for (table, col, ddl) in [
            ('settings','gcal_enabled',"ALTER TABLE settings ADD COLUMN gcal_enabled BOOLEAN DEFAULT 0"),
            ('settings','gcal_calendar_id',"ALTER TABLE settings ADD COLUMN gcal_calendar_id VARCHAR(400)"),
            ('invoice_status','invoice_number',"ALTER TABLE invoice_status ADD COLUMN invoice_number VARCHAR(120)"),
            ('role','vat_percent',"ALTER TABLE role ADD COLUMN vat_percent INTEGER DEFAULT %d" % DEFAULT_VAT_PERCENT),
            ('settings','favicon_url',"ALTER TABLE settings ADD COLUMN favicon_url VARCHAR(800)"),
            ('settings','currency_code',"ALTER TABLE settings ADD COLUMN currency_code VARCHAR(8) DEFAULT 'SEK'"),
        ]:
            try:
                if not column_exists(cur, table, col):
                    cur.execute(ddl)
            except sqlite3.OperationalError:
                pass
        con.commit()
    finally:
        con.close()

with app.app_context():
    db.create_all()
    ensure_schema()
    if Settings.query.count() == 0:
        s = Settings(company_logo_url=None, favicon_url=None, night_start_hour=0, night_end_hour=8,
                     google_calendar_embed_url=None, net_rate_percent=70.0,
                     login_enabled=False, gcal_enabled=False, gcal_calendar_id="primary")
        db.session.add(s); db.session.commit()

# ---------- Helpers ----------
def parse_percent(val, default):
    if val is None or val == '':
        return default
    try:
        s = str(val).replace(',', '.')
        return float(s)
    except Exception:
        return default

def get_settings():
    s = Settings.query.first()
    if not s:
        s = Settings(
            company_logo_url=None,
            favicon_url=None,
            google_calendar_embed_url=None,
            login_enabled=False,
            gcal_enabled=False,
            gcal_calendar_id='primary',
            night_start_hour=0,
            night_end_hour=8,
            net_rate_percent=70.0,
            currency_code='SEK'
        )
        db.session.add(s); db.session.commit()
    return s

@app.context_processor
def inject_globals():
    return {"settings": get_settings()}

@app.template_filter('fmt_money')
def fmt_money(value):
    try:
        v = float(value)
        s = f"{int(round(v)):,.0f}".replace(",", " ")
        return s
    except Exception:
        return value

def month_bounds(year:int, month:int):
    start = datetime(year, month, 1)
    end = start + relativedelta(months=1)
    return start, end

def get_invoice_status(client_id:int, year:int, month:int):
    rec = InvoiceStatus.query.filter_by(client_id=client_id, year=year, month=month).first()
    if not rec:
        rec = InvoiceStatus(client_id=client_id, year=year, month=month, sent=False, paid=False)
        db.session.add(rec); db.session.commit()
    return rec

def overlaps_night(start_dt, end_dt, ns, ne):
    t = start_dt
    while t <= end_dt:
        h = t.hour
        in_night = (h >= ns and h < ne) if ns < ne else (h >= ns or h < ne)
        if in_night: return True
        t = t + timedelta(hours=1)
    h = end_dt.hour
    in_night = (h >= ns and h < ne) if ns < ne else (h >= ns or h < ne)
    return in_night

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        s = get_settings()
        if s.login_enabled and not session.get('user'):
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return wrapper

# ---------- Google Calendar minimal helpers ----------
SCOPES = ["https://www.googleapis.com/auth/calendar"]

def credentials_path():
    # cherche credentials.json en priorité dans data/, sinon config/
    p1 = os.path.join(data_dir, "credentials.json")
    p2 = os.path.join(config_dir, "credentials.json")
    return p1 if os.path.exists(p1) else (p2 if os.path.exists(p2) else None)

def token_path():
    # cherche token.json d'abord dans data/, sinon dans config/ (et retourne data/ par défaut si aucun)
    p1 = os.path.join(data_dir, "token.json")
    p2 = os.path.join(config_dir, "token.json")
    if os.path.exists(p1): return p1
    if os.path.exists(p2): return p2
    return p1

def get_google_service():
    cred_file = credentials_path()
    if not cred_file: 
        return None
    creds = None
    tok = token_path()
    if os.path.exists(tok):
        creds = Credentials.from_authorized_user_file(tok, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            return None
    return build("calendar","v3", credentials=creds, cache_discovery=False)

def delete_gcal_event(job):
    s = get_settings()
    if not s.gcal_enabled: return
    if not job.gcal_event_id: return
    service = get_google_service()
    if not service: return
    cal_id = s.gcal_calendar_id or "primary"
    try:
        service.events().delete(calendarId=cal_id, eventId=job.gcal_event_id).execute()
    except Exception:
        pass

def create_gcal_event(job: "Job"):
    s = get_settings()
    if not s.gcal_enabled: return None
    service = get_google_service()
    if not service: return None
    cal_id = s.gcal_calendar_id or "primary"
    summary = f"{job.client.name} — {job.role.name}"
    description = job.detail or ""
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": job.start_dt.isoformat(), "timeZone": TIMEZONE},
        "end": {"dateTime": job.end_dt.isoformat(), "timeZone": TIMEZONE}
    }
    created = service.events().insert(calendarId=cal_id, body=body).execute()
    return created.get("id")

# ---------- Routes ----------
@app.route('/login', methods=['GET','POST'])
def login():
    s = get_settings()
    if not s.login_enabled:
        return redirect(url_for('jobs'))
    error = None
    if request.method == 'POST':
        pwd = request.form.get('password','')
        if s.login_password and pwd == s.login_password:
            session['user'] = 'admin'
            session.permanent = True
            nxt = request.args.get('next') or url_for('jobs')
            return redirect(nxt)
        else:
            error = "Invalid password."
    return render_template('login.html', app_name=APP_NAME, error=error)

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/healthz')
def healthz():
    return "ok", 200

@app.route('/')
@login_required
def jobs():
    now = datetime.now()
    upcoming_jobs = Job.query.filter(Job.end_dt >= now).order_by(Job.start_dt.asc()).all()
    past_jobs = Job.query.filter(Job.end_dt < now).order_by(Job.start_dt.desc()).limit(100).all()
    clients = Client.query.order_by(Client.name.asc()).all()
    roles_by_client = {}
    for c in clients:
        roles_by_client[str(c.id)] = [
            {"id": r.id, "name": r.name, "mode": r.mode, "rate": r.rate_sek}
            for r in c.roles if r.active
        ]
    return render_template('jobs.html',
                           app_name=APP_NAME, today=today_str(),
                           upcoming_jobs=upcoming_jobs, past_jobs=past_jobs,
                           clients=clients, roles_data=roles_by_client)

@app.route('/add-job', methods=['POST'])
@login_required
def add_job():
    start_dt = datetime.fromisoformat(request.form['start_dt'])
    end_dt = datetime.fromisoformat(request.form['end_dt'])
    client_id = int(request.form['client_id'])
    role_id = int(request.form['role_id'])
    vat_percent = int(request.form.get('vat_percent', DEFAULT_VAT_PERCENT))
    detail = request.form.get('detail','').strip()

    flags = []
    if Holiday.query.filter_by(date=start_dt.date()).first():
        flags.append("holiday")
    s = get_settings()
    ns, ne = s.night_start_hour, s.night_end_hour
    if overlaps_night(start_dt, end_dt, ns, ne):
        flags.append("night hours")
    if flags:
        detail = (detail + " " if detail else "") + "(" + " & ".join(flags) + ")"

    job = Job(client_id=client_id, role_id=role_id, start_dt=start_dt, end_dt=end_dt,
              vat_percent=vat_percent, detail=detail)
    db.session.add(job); db.session.commit()

    try:
        ev_id = create_gcal_event(job)
        if ev_id:
            job.gcal_event_id = ev_id
            db.session.commit()
    except Exception:
        pass

    return redirect(url_for('jobs'))

@app.route('/jobs/<int:job_id>/delete', methods=['POST'])
@login_required
def delete_job(job_id):
    job = Job.query.get_or_404(job_id)
    try:
        delete_gcal_event(job)
    except Exception:
        pass
    db.session.delete(job)
    db.session.commit()
    return redirect(url_for('jobs'))

@app.route('/monthly')
@login_required
def monthly_summary():
    year = int(request.args.get('year', datetime.now().year))
    month = int(request.args.get('month', datetime.now().month))
    start, end = month_bounds(year, month)
    jobs_q = Job.query.filter(Job.start_dt >= start, Job.start_dt < end).all()
    s = get_settings()
    net_factor = (s.net_rate_percent or 63.0)/100.0
    total_ht = sum(j.amount_sek for j in jobs_q)
    total_vat_amt = sum(((j.role.vat_percent if j.role and j.role.vat_percent is not None else j.vat_percent)/100.0) * j.amount_sek for j in jobs_q)
    total_gross = total_ht + total_vat_amt
    total_net = total_ht * net_factor
    # Annual total excl VAT
    ystart = datetime(year,1,1)
    yend = datetime(year+1,1,1)
    jobs_year = Job.query.filter(Job.start_dt >= ystart, Job.start_dt < yend).all()
    year_total_ht = sum(j.amount_sek for j in jobs_year)

    by_client = {}
    for j in jobs_q:
        by_client.setdefault(j.client_id, []).append(j)
    client_cards = []
    for cid, items in by_client.items():
        client = items[0].client
        ht = sum(i.amount_sek for i in items)
        vat_amt = sum(((i.role.vat_percent if i.role and i.role.vat_percent is not None else i.vat_percent)/100.0)*i.amount_sek for i in items)
        gross = ht + vat_amt
        net = ht * net_factor
        status = get_invoice_status(cid, year, month)
        client_cards.append({
            "client": client, "jobs": items, "ht": ht, "gross": gross, "net": net,
            "sent": status.sent, "paid": status.paid, "invoice_number": status.invoice_number
        })
    prev = datetime(year,month,1) - relativedelta(months=1)
    nxt  = datetime(year,month,1) + relativedelta(months=1)
    now = datetime.now()
    return render_template('monthly.html', app_name=APP_NAME, today=today_str(),
                           year=year, month=month, current_year=now.year, current_month=now.month,
                           month_label=f"{['','January','February','March','April','May','June','July','August','September','October','November','December'][month]} {year}", year_total_ht=year_total_ht,
                           net_rate_str=f"{(s.net_rate_percent or 63):.2f}%",
                           totals={"total_ht": total_ht, "total_gross": total_gross, "total_net": total_net},
                           client_cards=client_cards,
                           prev_year=prev.year, prev_month=prev.month,
                           next_year=nxt.year, next_month=nxt.month)

@app.route('/invoice/toggle', methods=['POST'])
@login_required
def toggle_invoice():
    cid = int(request.form['client_id'])
    year = int(request.form['year']); month = int(request.form['month'])
    field = request.form['field']
    status = get_invoice_status(cid, year, month)
    if field == 'sent': status.sent = not status.sent
    if field == 'paid': status.paid = not status.paid
    db.session.commit()
    return ('', 204)

@app.route('/invoice/number', methods=['POST'])
@login_required
def set_invoice_number():
    cid = int(request.form['client_id'])
    year = int(request.form['year']); month = int(request.form['month'])
    number = request.form.get('invoice_number','').strip()
    status = get_invoice_status(cid, year, month)
    status.invoice_number = number if number else None
    db.session.commit()
    return ('', 204)

@app.route('/clients')
@login_required
def clients_roles():
    clients = Client.query.order_by(Client.name.asc()).all()
    return render_template('clients.html', app_name=APP_NAME, today=today_str(), clients=clients)

@app.route('/clients/add', methods=['POST'])
@login_required
def add_client():
    c = Client(name=request.form['name'],
               default_vat_percent=int(request.form.get('default_vat_percent', DEFAULT_VAT_PERCENT)),
               logo_url=request.form.get('logo_url') or None)
    db.session.add(c); db.session.commit()
    return redirect(url_for('clients_roles'))

@app.route('/roles/add', methods=['POST'])
@login_required
def add_role():
    r = Role(client_id=int(request.form['client_id']),
             name=request.form['name'],
             mode=request.form['mode'],
             rate_sek=float(request.form['rate_sek']),
             vat_percent=int(request.form.get('vat_percent', DEFAULT_VAT_PERCENT)),
             active=True)
    db.session.add(r); db.session.commit()
    return redirect(url_for('clients_roles'))

@app.route('/roles/<int:role_id>/update', methods=['POST'])
@login_required
def update_role(role_id):
    r = Role.query.get_or_404(role_id)
    r.name = request.form['name']
    r.mode = request.form['mode']
    r.rate_sek = float(request.form['rate_sek'])
    r.vat_percent = int(request.form.get('vat_percent', r.vat_percent or DEFAULT_VAT_PERCENT))
    db.session.commit()
    return redirect(url_for('clients_roles'))

@app.route('/roles/<int:role_id>/archive', methods=['POST'])
@login_required
def archive_role(role_id):
    r = Role.query.get_or_404(role_id)
    r.active = False
    db.session.commit()
    return redirect(url_for('clients_roles'))

@app.route('/roles/<int:role_id>/unarchive', methods=['POST'])
@login_required
def unarchive_role(role_id):
    r = Role.query.get_or_404(role_id)
    r.active = True
    db.session.commit()
    return redirect(url_for('clients_roles'))

@app.route('/clients/<int:client_id>/edit', methods=['GET','POST'])
@login_required
def edit_client(client_id):
    c = Client.query.get_or_404(client_id)
    if request.method == 'POST':
        c.name = request.form['name']
        c.default_vat_percent = int(request.form.get('default_vat_percent', c.default_vat_percent))
        c.logo_url = request.form.get('logo_url') or None
        db.session.commit()
        return redirect(url_for('clients_roles'))
    return render_template('edit_client.html', app_name=APP_NAME, today=today_str(), client=c)

@app.route('/settings', methods=['GET','POST'])
@login_required

def settings_view():
    s = get_settings()
    if request.method == 'POST':
        form = request.form

        # ---- General settings (update only keys that are present) ----
        if 'company_logo_url' in form:
            s.company_logo_url = (form.get('company_logo_url') or None)
        if 'favicon_url' in form:
            s.favicon_url = (form.get('favicon_url') or None)
        if 'night_start_hour' in form:
            try:
                s.night_start_hour = int(form.get('night_start_hour', s.night_start_hour))
            except Exception:
                pass
        if 'night_end_hour' in form:
            try:
                s.night_end_hour = int(form.get('night_end_hour', s.night_end_hour))
            except Exception:
                pass
        if 'google_calendar_embed_url' in form:
            s.google_calendar_embed_url = (form.get('google_calendar_embed_url') or None)
        if 'net_rate_percent' in form:
            s.net_rate_percent = parse_percent(form.get('net_rate_percent'), s.net_rate_percent or 63.0)
        if 'login_enabled' in form:
            s.login_enabled = form.get('login_enabled','0') == '1'
        if 'login_password' in form:
            new_pwd = form.get('login_password','').strip()
            if new_pwd:
                s.login_password = new_pwd
        if 'currency_code' in form:
            s.currency_code = (form.get('currency_code') or s.currency_code or 'SEK')

        # ---- Google Calendar connection (update only if present) ----
        if 'gcal_enabled' in form:
            s.gcal_enabled = form.get('gcal_enabled','0') == '1'
        if 'gcal_calendar_id' in form:
            s.gcal_calendar_id = form.get('gcal_calendar_id') or "primary"

        db.session.commit()
        return redirect(url_for('settings_view'))
    holidays = Holiday.query.order_by(Holiday.date.asc()).all()
    return render_template('settings.html', app_name=APP_NAME, today=today_str(), settings=s, holidays=holidays)

# === NOUVELLE ROUTE : test connexion Google Calendar ===
@app.route('/settings/test-gcal', methods=['POST'])
@login_required
def settings_test_gcal():
    try:
        s = get_settings()
        if not s or not s.gcal_calendar_id:
            return jsonify({"ok": False, "msg": "No calendar ID configured."}), 400
        service = get_google_service()
        if not service:
            return jsonify({"ok": False, "msg": "No valid Google token/credentials."}), 400
        start = datetime.now() + timedelta(minutes=2)
        end   = start + timedelta(minutes=15)
        ev = {
            "summary": "ALR Test (from Settings)",
            "description": "Connectivity test from Settings",
            "start": {"dateTime": start.isoformat(), "timeZone": TIMEZONE},
            "end":   {"dateTime": end.isoformat(),   "timeZone": TIMEZONE},
        }
        created = service.events().insert(calendarId=s.gcal_calendar_id, body=ev).execute()
        return jsonify({"ok": True, "eventId": created.get("id")})
    except Exception as e:
        try:
            app.logger.exception("GCal test failed: %s", e)
        except Exception:
            pass
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route('/settings/upload-credentials', methods=['POST'], endpoint='upload_credentials')
@login_required
def upload_credentials():
    f = request.files.get('credentials')
    if f and f.filename.endswith('.json'):
        f.save(os.path.join(data_dir, "credentials.json"))
    return redirect(url_for('settings_view'))

# Holidays CRUD
@app.route('/settings/holiday/add', methods=['POST'], endpoint='settings_add_holiday')
@login_required
def settings_holiday_add():
    d = date.fromisoformat(request.form['date'])
    name = request.form['name']
    sur = request.form.get('surcharge_text','').strip()
    h = Holiday(date=d, name=name, surcharge_text=sur)
    db.session.add(h); db.session.commit()
    return redirect(url_for('settings_view'))

@app.route('/settings/holiday/<int:holiday_id>/update', methods=['POST'], endpoint='settings_update_holiday')
@login_required
def settings_holiday_update(holiday_id):
    h = Holiday.query.get_or_404(holiday_id)
    h.date = date.fromisoformat(request.form['date'])
    h.name = request.form['name']
    h.surcharge_text = request.form.get('surcharge_text','').strip()
    db.session.commit()
    return redirect(url_for('settings_view'))

@app.route('/settings/holiday/<int:holiday_id>/delete', methods=['POST'], endpoint='settings_delete_holiday')
@login_required
def settings_holiday_delete(holiday_id):
    h = Holiday.query.get_or_404(holiday_id)
    db.session.delete(h); db.session.commit()
    return redirect(url_for('settings_view'))

# Minimal Google Calendar endpoints to avoid 404s
@app.route('/gcal/connect')
@login_required
def gcal_connect():
    # In a production-ready flow you would start OAuth here.
    # For now, redirect back to settings.
    return redirect(url_for('settings_view'))

@app.route('/gcal/disconnect')
@login_required
def gcal_disconnect():
    try:
        os.remove(os.path.join(data_dir, "token.json"))
    except Exception:
        pass
    return redirect(url_for('settings_view'))

@app.route('/gcal/create-calendar')
@login_required
def gcal_create_calendar():
    s = get_settings()
    service = get_google_service()
    if service:
        try:
            cal = {"summary":"Freelancer Admin App", "timeZone": TIMEZONE}
            created = service.calendars().insert(body=cal).execute()
            s.gcal_calendar_id = created.get('id')
            db.session.commit()
        except Exception:
            pass
    return redirect(url_for('settings_view'))

@app.route('/calendar')
@login_required
def calendar_view():
    s = get_settings()
    return render_template('calendar.html', app_name=APP_NAME, today=today_str(), embed_url=s.google_calendar_embed_url)

# Statistics API (net revenue + per-chart ordering biggest->smallest)
@app.route('/api/stats/<int:year>')
@login_required
def api_stats(year):
    months = list(range(1,13))
    buckets = { m: [] for m in months }
    jobs_year = Job.query.filter(db.extract('year', Job.start_dt)==year).all()
    for j in jobs_year:
        buckets[j.start_dt.month].append(j)
    clients_all = sorted({ j.client.name for j in jobs_year })
    s = get_settings()
    net_factor = (s.net_rate_percent or 63.0)/100.0
    def totals_by_client(metric):
        totals = {c:0 for c in clients_all}
        for c in clients_all:
            for m in months:
                arr = [j for j in buckets[m] if j.client.name==c]
                if metric=='hours':
                    v = sum(j.duration_hours for j in arr)
                elif metric=='jobs':
                    v = len(arr)
                elif metric=='revenue':
                    v = sum(j.amount_sek for j in arr) * net_factor
                else:
                    v = 0
                totals[c] += v
        return totals
    totals_hours = totals_by_client('hours')
    totals_jobs = totals_by_client('jobs')
    totals_rev  = totals_by_client('revenue')
    clients_hours = sorted(clients_all, key=lambda c: totals_hours[c], reverse=True)
    clients_jobs  = sorted(clients_all, key=lambda c: totals_jobs[c],  reverse=True)
    clients_rev   = sorted(clients_all, key=lambda c: totals_rev[c],   reverse=True)
    def series(metric, clients_order):
        out = {c:[] for c in clients_order}
        for m in months:
            arr = buckets[m]
            for c in clients_order:
                jobs = [j for j in arr if j.client.name==c]
                if metric=='hours':
                    v = sum(j.duration_hours for j in jobs)
                elif metric=='jobs':
                    v = len(jobs)
                elif metric=='revenue':
                    v = sum(j.amount_sek for j in jobs) * net_factor
                else:
                    v = 0
                if isinstance(v, float):
                    v = round(v)
                out[c].append(v)
        return out
    return jsonify({
      "months": ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],
      "clients_hours": clients_hours,
      "clients_jobs": clients_jobs,
      "clients_revenue": clients_rev,
      "hours": series('hours', clients_hours),
      "jobs": series('jobs', clients_jobs),
      "revenue": series('revenue', clients_rev)
    })

@app.route('/statistics')
@login_required
def statistics():
    # years present in DB (fallback current year)
    years = sorted({ datetime.now().year })
    all_jobs = Job.query.all()
    if all_jobs:
        years = sorted({ j.start_dt.year for j in all_jobs })
    year = int(request.args.get('year', datetime.now().year))

    # Totals to display
    s = get_settings()
    net_factor = (s.net_rate_percent or 63.0)/100.0
    jobs_year = [j for j in all_jobs if j.start_dt.year == year]
    total_hours = round(sum(j.duration_hours for j in jobs_year))
    total_jobs = len(jobs_year)
    total_revenue_net = round(sum(j.amount_sek for j in jobs_year) * net_factor)

    return render_template('stats.html', app_name=APP_NAME, today=today_str(),
                           years=years, year=year,
                           totals={"hours_year": total_hours, "jobs_year": total_jobs, "revenue_year": total_revenue_net})

@app.route('/api/holiday')
@login_required
def api_holiday():
    d = request.args.get('date')
    try:
        dt = datetime.fromisoformat(d)
    except Exception:
        return jsonify({"is_holiday": False})
    h = Holiday.query.filter_by(date=dt.date()).first()
    return jsonify({"is_holiday": bool(h), "name": (h.name if h else None), "surcharge_text": (h.surcharge_text if h else None)})

@app.route('/api/settings')
@login_required
def api_settings():
    s = get_settings()
    return jsonify({
        "night_start_hour": s.night_start_hour,
        "night_end_hour": s.night_end_hour
    })

@app.after_request
def no_cache(resp):
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

if __name__ == '__main__':
    if not os.path.exists(db_path):
        open(db_path, 'a').close()
    app.run(host='0.0.0.0', port=8080)