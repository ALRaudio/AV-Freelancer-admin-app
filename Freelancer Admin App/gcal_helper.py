# gcal_helper.py — minimal, ne touche pas à ta DB
import os, json
import pytz
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

TZ = "Europe/Stockholm"

def _load_gcal_service(app_root):
    token_path = os.path.join(app_root, "config", "token.json")
    with open(token_path, "r", encoding="utf-8") as f:
        t = json.load(f)
    creds = Credentials(
        token=t.get("token"),
        refresh_token=t.get("refresh_token"),
        token_uri=t.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=t.get("client_id"),
        client_secret=t.get("client_secret"),
        scopes=t.get("scopes") or ["https://www.googleapis.com/auth/calendar"],
    )
    if not creds.valid:
        creds.refresh(Request())
    return build("calendar", "v3", credentials=creds, cache_discovery=False)

def create_gcal_event(app_root, calendar_id, job, client_name, role_name):
    """job.start_dt/end_dt doivent être des datetime (tz naïf) ou strings '%Y-%m-%d %H:%M'."""
    service = _load_gcal_service(app_root)
    tz = pytz.timezone(TZ)

    def to_dt(x):
        if isinstance(x, datetime):
            return x
        return datetime.strptime(x, "%Y-%m-%d %H:%M")

    sdt = tz.localize(to_dt(job.start_dt))
    edt = tz.localize(to_dt(job.end_dt))

    body = {
        "summary": f"{client_name} - {role_name}",
        "description": (job.detail or "").strip(),
        "start": {"dateTime": sdt.isoformat(), "timeZone": TZ},
        "end":   {"dateTime": edt.isoformat(), "timeZone": TZ},
    }
    ev = service.events().insert(calendarId=calendar_id, body=body).execute()
    return ev.get("id")

def test_gcal_create(app_root, calendar_id):
    """Crée un petit évènement test dans 2 minutes."""
    service = _load_gcal_service(app_root)
    tz = pytz.timezone(TZ)
    start = tz.localize(datetime.now() + timedelta(minutes=2))
    end   = tz.localize(datetime.now() + timedelta(minutes=17))
    ev = {
        "summary": "ALR Test (from Settings)",
        "description": "Connectivity test from Settings",
        "start": {"dateTime": start.isoformat(), "timeZone": TZ},
        "end":   {"dateTime": end.isoformat(), "timeZone": TZ},
    }
    created = service.events().insert(calendarId=calendar_id, body=ev).execute()
    return created.get("id")