"""Email delivery with visible failures.

Three ways to send, tried in this order (first one configured wins):

  1. Resend HTTPS API   HB_RESEND_API_KEY   ← most reliable on cloud hosts
  2. Brevo  HTTPS API   HB_BREVO_API_KEY
  3. SMTP               HB_SMTP_HOST / HB_SMTP_USER / HB_SMTP_PASS

Why the HTTPS options exist: some hosts throttle or block outbound SMTP, and
when that happens SMTP fails silently in a background thread — exactly the
"no email ever arrives and there's no clue why" trap. So:

  * OTP emails are sent BLOCKING, so the API reports a real failure instead
    of pretending everything is fine.
  * The last attempt (ok/failed + reason, never credentials) is remembered
    and exposed at GET /health/mail for instant diagnosis.
"""
import json
import os
import smtplib
import ssl
import threading
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr

BRAND = "#FF5C8A"

#: Mail APIs sit behind Cloudflare, which blocks requests that don't identify
#: themselves (it answers "error code: 1010"). A real User-Agent avoids that.
UA = "HealthBuddy/1.0 (+https://github.com/healthbuddy; python-urllib)"

#: last delivery attempt — read by /health/mail (contains no secrets)
LAST_RESULT = {"attempted": False}


def config():
    user = os.environ.get("HB_SMTP_USER", "").strip()
    return {
        "resend_key": os.environ.get("HB_RESEND_API_KEY", "").strip(),
        "brevo_key": os.environ.get("HB_BREVO_API_KEY", "").strip(),
        "host": os.environ.get("HB_SMTP_HOST", "").strip(),
        "port": int(os.environ.get("HB_SMTP_PORT", "587") or 587),
        "user": user,
        "password": os.environ.get("HB_SMTP_PASS", ""),
        "from_addr": (os.environ.get("HB_MAIL_FROM", "").strip() or user
                      or "onboarding@resend.dev"),
        "from_name": os.environ.get("HB_MAIL_FROM_NAME", "HealthBuddy"),
    }


def provider():
    c = config()
    if c["resend_key"]:
        return "resend"
    if c["brevo_key"]:
        return "brevo"
    if c["host"] and c["user"] and c["password"]:
        return "smtp"
    return None


def is_configured():
    return provider() is not None


def status():
    """Safe summary for the diagnostics endpoint — no keys or passwords."""
    c = config()
    return {
        "provider": provider() or "none",
        "configured": is_configured(),
        "from": c["from_addr"] or None,
        "smtp_host": c["host"] or None,
        "smtp_port": c["port"] if c["host"] else None,
        "smtp_user_set": bool(c["user"]),
        "smtp_pass_set": bool(c["password"]),
        "last_attempt": LAST_RESULT,
    }


# --------------------------------------------------------------- transports
def _send_resend(cfg, to_addr, subject, text, html):
    payload = json.dumps({
        "from": f"{cfg['from_name']} <{cfg['from_addr']}>",
        "to": [to_addr], "subject": subject, "text": text, "html": html or text,
    }).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload, method="POST",
        headers={"Authorization": f"Bearer {cfg['resend_key']}",
                 "Content-Type": "application/json",
                 "Accept": "application/json",
                 "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


def _send_brevo(cfg, to_addr, subject, text, html):
    payload = json.dumps({
        "sender": {"name": cfg["from_name"], "email": cfg["from_addr"]},
        "to": [{"email": to_addr}], "subject": subject,
        "textContent": text, "htmlContent": html or text,
    }).encode()
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email", data=payload, method="POST",
        headers={"api-key": cfg["brevo_key"], "Content-Type": "application/json",
                 "Accept": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


def _send_smtp(cfg, to_addr, subject, text, html):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg["from_name"], cfg["from_addr"]))
    msg["To"] = to_addr
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    context = ssl.create_default_context()
    if cfg["port"] == 465:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=20, context=context) as s:
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as s:
            s.ehlo()
            s.starttls(context=context)
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)


def _explain(exc):
    """Turn provider errors into something a human can act on."""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            detail = exc.read().decode()[:200]
        except Exception:
            detail = ""
        if "1010" in detail:
            return ("Blocked by Cloudflare before reaching the mail provider "
                    "(error 1010) — the request needs a User-Agent header. "
                    "Update to the latest build.")
        if exc.code == 403 and "testing emails" in detail:
            return ("Resend is in test mode: it will only deliver to the email "
                    "address you signed up with. Send the test there, or verify "
                    "a domain at resend.com/domains to reach anyone.")
        if "sender" in detail.lower() and "not valid" in detail.lower():
            return ("Brevo doesn't recognise the sender address yet. Add it under "
                    "Senders, Domains & Dedicated IPs → Senders, click the link in "
                    "the confirmation email, then set HB_MAIL_FROM to that address.")
        if exc.code in (401, 403):
            return (f"API key rejected ({exc.code}). Check the key you set "
                    f"(HB_BREVO_API_KEY or HB_RESEND_API_KEY). {detail}")
        if exc.code == 422:
            return ("Sender address not allowed yet — verify your domain, or send "
                    f"from onboarding@resend.dev while testing. {detail}")
        return f"HTTP {exc.code} from the mail provider. {detail}"
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return ("Gmail rejected the login. Use a 16-character App Password (not your "
                "normal password), delete the spaces, and make sure 2-Step "
                "Verification is ON for that account.")
    if isinstance(exc, (TimeoutError, OSError)) and "timed out" in str(exc).lower():
        return ("Connection to the mail server timed out — this host may block SMTP. "
                "Switch to the Resend API (HB_RESEND_API_KEY).")
    return f"{type(exc).__name__}: {exc}"


def send(to_addr, subject, text_body, html_body=None, logger=None, blocking=True):
    """Returns (ok, error_message). Never raises — callers decide what to do."""
    global LAST_RESULT
    prov = provider()
    if prov is None:
        LAST_RESULT = {"attempted": True, "ok": False, "provider": "none",
                       "error": "No mail provider configured (set HB_RESEND_API_KEY "
                                "or the HB_SMTP_* variables)."}
        if logger:
            logger.warning("[mail] not configured — would have sent %r to %s", subject, to_addr)
        return False, LAST_RESULT["error"]

    cfg = config()
    fn = {"resend": _send_resend, "brevo": _send_brevo, "smtp": _send_smtp}[prov]

    def attempt():
        global LAST_RESULT
        try:
            fn(cfg, to_addr, subject, text_body, html_body)
            LAST_RESULT = {"attempted": True, "ok": True, "provider": prov, "to": _mask(to_addr)}
            if logger:
                logger.info("[mail] sent %r to %s via %s", subject, to_addr, prov)
            return True, None
        except Exception as exc:
            reason = _explain(exc)
            LAST_RESULT = {"attempted": True, "ok": False, "provider": prov,
                           "to": _mask(to_addr), "error": reason}
            if logger:
                logger.error("[mail] FAILED via %s to %s: %s", prov, to_addr, reason)
            return False, reason

    if blocking:
        return attempt()
    threading.Thread(target=attempt, daemon=True).start()
    return True, None


def _mask(addr):
    name, _, domain = (addr or "").partition("@")
    return (name[:2] + "***@" + domain) if domain else "***"


# ------------------------------------------------------------------ templates
def _shell(title, intro, code, outro):
    return f"""<!DOCTYPE html>
<html><body style="margin:0;background:#F6F1EA;font-family:'Segoe UI',Helvetica,Arial,sans-serif">
  <div style="max-width:480px;margin:32px auto;background:#fff;border-radius:18px;overflow:hidden;
              box-shadow:0 6px 24px rgba(0,0,0,.08)">
    <div style="background:linear-gradient(135deg,#FF8A5C,{BRAND});padding:22px 26px;color:#fff">
      <div style="font-size:22px;font-weight:800">🌱 HealthBuddy</div>
    </div>
    <div style="padding:26px">
      <h1 style="margin:0 0 10px;font-size:20px;color:#241028">{title}</h1>
      <p style="margin:0 0 20px;color:#5b5566;line-height:1.5">{intro}</p>
      <div style="text-align:center;margin:24px 0">
        <div style="display:inline-block;letter-spacing:10px;font-size:34px;font-weight:800;
                    color:#241028;background:#F6F1EA;border-radius:14px;padding:16px 22px">{code}</div>
      </div>
      <p style="margin:0;color:#8a8398;font-size:13px;line-height:1.5">{outro}</p>
    </div>
  </div>
</body></html>"""


def send_verification_code(to_addr, code, logger=None):
    text = (f"Welcome to HealthBuddy!\n\nYour verification code is: {code}\n\n"
            "It expires in 10 minutes. If you didn't sign up, you can ignore this email.")
    html = _shell("Confirm your email 🌱",
                  "Pop this code into the app to finish setting up your account.",
                  code, "This code expires in 10 minutes. Didn't sign up? Ignore this email.")
    return send(to_addr, "Your HealthBuddy verification code", text, html, logger)


def send_reset_code(to_addr, code, logger=None):
    text = (f"Password reset for HealthBuddy.\n\nYour reset code is: {code}\n\n"
            "It expires in 10 minutes. If you didn't ask for this, ignore this email.")
    html = _shell("Reset your password 🔑",
                  "Enter this code in the app, then choose a new password.",
                  code, "This code expires in 10 minutes. Didn't request it? "
                        "Ignore this email — your password hasn't changed.")
    return send(to_addr, "Your HealthBuddy password reset code", text, html, logger)
