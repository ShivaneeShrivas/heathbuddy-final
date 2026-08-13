# 📧 Making the OTP emails actually arrive (15 minutes, free)

Your app now emails 6-digit codes for signup verification and password
resets. The code is written and tested — it just needs an email account to
send *through*. Until you do this, codes appear in the Render logs instead of
inboxes (so the app still works, but only for you).

**Recommended: Gmail with an "App Password"** — free, 5 minutes, fine for a
few hundred users a day.

## Step 1 — Get a Gmail App Password

An App Password is a special 16-character password for apps. Your normal
Gmail password will NOT work (Google blocks it).

1. Use a Gmail account for the app (a fresh one like
   `healthbuddy.app@gmail.com` is tidier than your personal address).
2. That account needs 2-Step Verification ON:
   https://myaccount.google.com/signinoptions/two-step-verification
3. Then open https://myaccount.google.com/apppasswords
4. App name: type `HealthBuddy` → **Create**.
5. Google shows 16 characters like `abcd efgh ijkl mnop`. Copy it.
   **Remove the spaces** → `abcdefghijklmnop`. You can't see it again later.

## Step 2 — Add 5 settings to Render

Render dashboard → your `healthbuddy` service → **Environment** →
**Add Environment Variable** (five times):

| Key | Value |
|---|---|
| `HB_SMTP_HOST` | `smtp.gmail.com` |
| `HB_SMTP_PORT` | `587` |
| `HB_SMTP_USER` | the full Gmail address you used |
| `HB_SMTP_PASS` | the 16-character App Password, no spaces |
| `HB_MAIL_FROM_NAME` | `HealthBuddy` |

Also set this one, so codes stop being exposed in API responses once real
email works:

| Key | Value |
|---|---|
| `HB_EXPOSE_RESET_TOKEN` | `0` |

Click **Save changes** — Render restarts automatically (~1 min).

## Step 3 — Test it

1. Open your app → **Get started** → register with a real email address you
   can check.
2. Within ~30 seconds an email titled *"Your HealthBuddy verification code"*
   arrives with a big 6-digit code.
3. Type it in → account created. Type a wrong one → **"Wrong OTP."**
4. Sign out → **Forgot password?** → enter that email → code arrives → set a
   new password.

**Nothing arrives?** Render → Logs, and search for `[mail]`:
- `[mail] sent ...` → sent successfully; check the spam folder.
- `[mail] FAILED ... Username and Password not accepted` → the App Password
  is wrong, has spaces, or 2-Step Verification isn't on.
- `[mail] not configured` → a variable name is misspelled; they're
  case-sensitive.

## If you outgrow Gmail (500 emails/day limit)

Same five variables, different values — nothing in the code changes:

**Brevo** (300/day free, no card): sign up → SMTP & API → SMTP settings.
`HB_SMTP_HOST=smtp-relay.brevo.com`, `HB_SMTP_PORT=587`, user = the login
Brevo shows, pass = the SMTP key.

**Resend** (3,000/month free): `HB_SMTP_HOST=smtp.resend.com`,
`HB_SMTP_PORT=587`, `HB_SMTP_USER=resend`, pass = your API key. Best
deliverability, but wants a domain you own.

## Good to know

- Emails send on a background thread, so signup never freezes waiting for
  Gmail.
- Codes: 6 digits, expire in 10 minutes, single use, 5 wrong guesses max,
  60-second gap between resends, 5 per hour per email. That's what stops
  someone using your app to spam a stranger's inbox.
- Existing accounts are untouched — they're already marked verified, so
  nobody gets locked out by this change. Only new signups see the OTP step.
