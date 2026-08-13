"""One-time codes for email verification and password reset.

Security choices, all deliberate:
- Only an HMAC of the code is stored, keyed by SECRET_KEY — a leaked DB row
  can't be turned back into a working code.
- 6 digits, 10-minute expiry, single use.
- Max 5 wrong guesses per code, then it dies (blocks brute forcing).
- 60-second cooldown between sends and max 5 sends per email per hour
  (stops the app being used as a spam cannon at someone's inbox).
"""
import hmac
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app

from ..db import execute, query

CODE_TTL_MINUTES = 10
MAX_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60
MAX_SENDS_PER_HOUR = 5
PURPOSES = ("verify", "reset")


class OtpError(Exception):
    """Carries a message that's safe (and friendly) to show the user."""


def _now():
    return datetime.now(timezone.utc)


def _hash(code, email, purpose):
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, f"{purpose}:{email}:{code}".encode(), hashlib.sha256).hexdigest()


def normalize_email(raw):
    return (raw or "").strip().lower()


def create(email, purpose):
    """Issue a fresh code, invalidating any earlier unused one for this purpose."""
    if purpose not in PURPOSES:
        raise ValueError("bad purpose")
    email = normalize_email(email)

    recent = query("""SELECT created_at FROM email_otps
                      WHERE email=? AND purpose=?
                      ORDER BY id DESC LIMIT 1""", (email, purpose), one=True)
    if recent:
        created = datetime.fromisoformat(recent["created_at"]).replace(tzinfo=timezone.utc)
        waited = (_now() - created).total_seconds()
        if waited < RESEND_COOLDOWN_SECONDS:
            raise OtpError(f"Hang on {int(RESEND_COOLDOWN_SECONDS - waited)}s before asking for another code.")

    sent_last_hour = query("""SELECT COUNT(*) AS n FROM email_otps
                              WHERE email=? AND purpose=?
                                AND created_at >= datetime('now','-1 hour')""",
                           (email, purpose), one=True)["n"]
    if sent_last_hour >= MAX_SENDS_PER_HOUR:
        raise OtpError("That's a lot of codes for one hour. Try again a bit later.")

    execute("UPDATE email_otps SET used_at=datetime('now') WHERE email=? AND purpose=? AND used_at IS NULL",
            (email, purpose))

    code = f"{secrets.randbelow(1000000):06d}"
    expires = _now() + timedelta(minutes=CODE_TTL_MINUTES)
    execute("""INSERT INTO email_otps (email, purpose, code_hash, expires_at, created_at)
               VALUES (?,?,?,?,datetime('now'))""",
            (email, purpose, _hash(code, email, purpose), expires.isoformat()))
    return code


def verify(email, purpose, code):
    """Consume the code. Raises OtpError with a friendly message on failure."""
    email = normalize_email(email)
    code = (code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise OtpError("Codes are 6 digits — check the email and try again.")

    row = query("""SELECT * FROM email_otps
                   WHERE email=? AND purpose=? AND used_at IS NULL
                   ORDER BY id DESC LIMIT 1""", (email, purpose), one=True)
    if row is None:
        raise OtpError("No active code for that email. Ask for a new one.")

    expires = datetime.fromisoformat(row["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < _now():
        execute("UPDATE email_otps SET used_at=datetime('now') WHERE id=?", (row["id"],))
        raise OtpError("That code has expired. Send yourself a fresh one.")

    if row["attempts"] >= MAX_ATTEMPTS:
        execute("UPDATE email_otps SET used_at=datetime('now') WHERE id=?", (row["id"],))
        raise OtpError("Too many wrong tries. Request a new code.")

    if not hmac.compare_digest(row["code_hash"], _hash(code, email, purpose)):
        execute("UPDATE email_otps SET attempts=attempts+1 WHERE id=?", (row["id"],))
        left = MAX_ATTEMPTS - (row["attempts"] + 1)
        raise OtpError("Wrong OTP." + (f" {left} tries left." if left > 0 else " Request a new code."))

    execute("UPDATE email_otps SET used_at=datetime('now') WHERE id=?", (row["id"],))
    return True
