"""
core/calendar_sync.py
---------------------
Google Calendar and Outlook (Microsoft Graph) integration for Plia.

Dependencies (install into your conda env):
    pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
    pip install msal requests

Tokens are stored locally in data/google_token.json and data/outlook_token.json.
They are refreshed automatically on each sync — the user only has to log in once.
"""

import os
import json
import webbrowser
import datetime
from pathlib import Path

# ── Token storage paths ───────────────────────────────────────────────────────
_DATA_DIR         = Path(__file__).parent.parent / "data"
_GOOGLE_TOKEN     = _DATA_DIR / "google_token.json"
_GOOGLE_CREDS     = _DATA_DIR / "google_client_secret.json"
_OUTLOOK_TOKEN    = _DATA_DIR / "outlook_token.json"

_GOOGLE_SCOPES    = ["https://www.googleapis.com/auth/calendar.readonly"]
_OUTLOOK_SCOPES   = ["Calendars.Read", "offline_access"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _ensure_data_dir():
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# GOOGLE CALENDAR
# =============================================================================

def google_auth_flow(client_id: str, client_secret: str):
    """
    Run the Google OAuth 2.0 flow.
    Opens the browser, waits for the redirect, and saves the token.
    Raises on failure.
    """
    _ensure_data_dir()

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise RuntimeError(
            "google-auth-oauthlib not installed.\n"
            "Run: pip install google-auth google-auth-oauthlib google-api-python-client"
        )

    # Build a minimal client-secrets dict in memory
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes=_GOOGLE_SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)

    # Persist token
    with open(_GOOGLE_TOKEN, "w") as f:
        f.write(creds.to_json())

    print("[GoogleCalendar] Authorisation complete, token saved.")


def google_revoke():
    """Delete saved Google token."""
    if _GOOGLE_TOKEN.exists():
        _GOOGLE_TOKEN.unlink()
    print("[GoogleCalendar] Token deleted.")


def fetch_google_events(days_ahead: int = 14) -> list:
    """
    Return a list of upcoming Google Calendar events as normalised dicts.
    Each dict has: title, start, end, source='google', calendar.
    """
    if not _GOOGLE_TOKEN.exists():
        return []

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        print("[GoogleCalendar] google-api packages not installed.")
        return []

    creds = Credentials.from_authorized_user_file(str(_GOOGLE_TOKEN), _GOOGLE_SCOPES)

    # Auto-refresh if expired
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(_GOOGLE_TOKEN, "w") as f:
            f.write(creds.to_json())

    service  = build("calendar", "v3", credentials=creds)
    now      = datetime.datetime.utcnow().isoformat() + "Z"
    end_time = (datetime.datetime.utcnow() + datetime.timedelta(days=days_ahead)).isoformat() + "Z"

    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            timeMax=end_time,
            maxResults=50,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = []
    for item in result.get("items", []):
        start_raw = item["start"].get("dateTime", item["start"].get("date", ""))
        end_raw   = item["end"].get("dateTime",   item["end"].get("date",   ""))
        events.append({
            "title":     item.get("summary", "Untitled"),
            "start":     _fmt_dt(start_raw),
            "start_iso": start_raw,           # raw ISO — used for date matching
            "end":       _fmt_dt(end_raw),
            "end_iso":   end_raw,
            "source":    "google",
            "calendar":  "Primary",
            "url":       item.get("htmlLink", ""),
        })

    return events


# =============================================================================
# OUTLOOK / MICROSOFT 365
# =============================================================================

def outlook_auth_flow(client_id: str, tenant_id: str = "common"):
    """
    Run the Microsoft Device Code flow (no redirect URI needed).
    Prints a code to the console and opens the browser for the user.
    Saves the token on success. Raises on failure.
    """
    _ensure_data_dir()

    try:
        import msal
    except ImportError:
        raise RuntimeError(
            "msal not installed.\n"
            "Run: pip install msal"
        )

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.PublicClientApplication(client_id, authority=authority)

    flow = app.initiate_device_flow(scopes=_OUTLOOK_SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Could not initiate device flow: {flow.get('error_description', '')}")

    print(f"[Outlook] {flow['message']}")
    webbrowser.open(flow["verification_uri"])

    result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        raise RuntimeError(result.get("error_description", "Unknown error"))

    # Save token + client info for future refreshes
    token_data = {
        "client_id":  client_id,
        "tenant_id":  tenant_id,
        "token":      result,
    }
    with open(_OUTLOOK_TOKEN, "w") as f:
        json.dump(token_data, f, indent=2)

    print("[Outlook] Authorisation complete, token saved.")


def outlook_revoke():
    """Delete saved Outlook token."""
    if _OUTLOOK_TOKEN.exists():
        _OUTLOOK_TOKEN.unlink()
    print("[Outlook] Token deleted.")


def fetch_outlook_events(days_ahead: int = 14) -> list:
    """
    Return a list of upcoming Outlook Calendar events as normalised dicts.
    Each dict has: title, start, end, source='outlook', calendar.
    """
    if not _OUTLOOK_TOKEN.exists():
        return []

    try:
        import msal
        import requests as req
    except ImportError:
        print("[Outlook] msal/requests not installed.")
        return []

    with open(_OUTLOOK_TOKEN) as f:
        saved = json.load(f)

    client_id = saved["client_id"]
    tenant_id = saved["tenant_id"]
    token     = saved["token"]

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app       = msal.PublicClientApplication(client_id, authority=authority)

    # Try silent refresh
    accounts = app.get_accounts()
    result   = None
    if accounts:
        result = app.acquire_token_silent(_OUTLOOK_SCOPES, account=accounts[0])

    if not result:
        # Use the saved refresh token directly
        result = app.acquire_token_by_refresh_token(
            token.get("refresh_token", ""),
            scopes=_OUTLOOK_SCOPES
        )

    if "access_token" not in result:
        print(f"[Outlook] Token refresh failed: {result.get('error_description')}")
        return []

    # Persist refreshed token
    saved["token"] = result
    with open(_OUTLOOK_TOKEN, "w") as f:
        json.dump(saved, f, indent=2)

    # Query Microsoft Graph
    now      = datetime.datetime.utcnow().isoformat() + "Z"
    end_time = (datetime.datetime.utcnow() + datetime.timedelta(days=days_ahead)).isoformat() + "Z"

    headers = {"Authorization": f"Bearer {result['access_token']}"}
    params  = {
        "$orderby":   "start/dateTime",
        "$top":       50,
        "startDateTime": now,
        "endDateTime":   end_time,
    }
    resp = req.get(
        "https://graph.microsoft.com/v1.0/me/calendarview",
        headers=headers,
        params=params,
        timeout=15,
    )

    if resp.status_code != 200:
        print(f"[Outlook] Graph API error {resp.status_code}: {resp.text[:200]}")
        return []

    events = []
    for item in resp.json().get("value", []):
        start_raw = item.get("start", {}).get("dateTime", "")
        end_raw   = item.get("end",   {}).get("dateTime", "")
        events.append({
            "title":     item.get("subject", "Untitled"),
            "start":     _fmt_dt(start_raw),
            "start_iso": start_raw,           # raw ISO — used for date matching
            "end":       _fmt_dt(end_raw),
            "end_iso":   end_raw,
            "source":    "outlook",
            "calendar":  item.get("calendar", {}).get("name", "Calendar"),
            "url":       item.get("webLink", ""),
        })

    return events


# =============================================================================
# Shared helpers
# =============================================================================

def _fmt_dt(raw: str) -> str:
    """Format an ISO datetime string to a human-readable form."""
    if not raw:
        return ""
    try:
        # Strip trailing Z or timezone offset for parsing
        clean = raw.replace("Z", "").split("+")[0].split(".")[0]
        dt    = datetime.datetime.fromisoformat(clean)
        return dt.strftime("%a %d %b, %I:%M %p")
    except Exception:
        return raw
