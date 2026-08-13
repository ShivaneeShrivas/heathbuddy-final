# 📧 No OTP email arriving? Fix it in 10 minutes

## STEP 1 — Ask the app what's wrong (30 seconds)

Open this in a browser (your Render address + `/health/mail`):

```
https://YOUR-APP.onrender.com/health/mail
```

Read the `provider` line:

| What you see | What it means | Do this |
|---|---|---|
| `"provider": "none"` | **No mail settings reached the server at all** — this is almost certainly your case | Step 2 |
| `"provider": "smtp"` + `last_attempt.error` about Gmail login | App Password wrong / has spaces / 2-Step not on | Step 3 |
| `"provider": "smtp"` + `error` says timed out | The host is blocking SMTP | Step 2 (Resend) |
| `"provider": "resend"`, `last_attempt.ok: true` | Email IS being sent | Check spam; check the address |

**Send yourself a real test message** by adding your email:

```
https://YOUR-APP.onrender.com/health/mail?to=you@example.com
```

The answer includes `test_send` with either `ok: true` or the exact reason it
failed. That one link replaces all guessing.

---

## STEP 2 — The fast, reliable route: Resend (5 minutes, free)

Gmail SMTP works but is fiddly, and cloud hosts sometimes block SMTP ports
entirely. Resend sends over normal HTTPS, so it can't be blocked. Free tier:
3,000 emails/month.

1. Go to **https://resend.com** → Sign up (GitHub login works, no card).
2. Left sidebar → **API Keys** → **Create API Key** → name it `healthbuddy`
   → permission "Sending access" → **Create**.
3. Copy the key (starts with `re_`). It's shown once.
4. Render dashboard → your service → **Environment** → **Add Environment
   Variable**:

   | Key | Value |
   |---|---|
   | `HB_RESEND_API_KEY` | the `re_...` key |
   | `HB_MAIL_FROM` | `onboarding@resend.dev` |
   | `HB_MAIL_FROM_NAME` | `HealthBuddy` |

5. **Save changes** → Render restarts (~1 min).
6. Test: `https://YOUR-APP.onrender.com/health/mail?to=you@example.com`
   → expect `"ok": true` and an email within seconds.

About `onboarding@resend.dev`: it's Resend's shared test sender, so you can
send immediately without owning a domain. It works for everyone during your
pilot. Later, if you buy a domain, add it in Resend → Domains and change
`HB_MAIL_FROM` to your own address.

*(If you'd rather stick with Gmail, keep the `HB_SMTP_*` variables and just
remove `HB_RESEND_API_KEY` — the app picks whichever is configured, Resend
first.)*

---

## STEP 3 — If you're keeping Gmail SMTP

Check each of these in Render → Environment (spelling is case-sensitive):

| Key | Correct value |
|---|---|
| `HB_SMTP_HOST` | `smtp.gmail.com` |
| `HB_SMTP_PORT` | `587` |
| `HB_SMTP_USER` | full address, e.g. `healthbuddy.app@gmail.com` |
| `HB_SMTP_PASS` | 16 characters, **no spaces**, from myaccount.google.com/apppasswords |
| `HB_MAIL_FROM_NAME` | `HealthBuddy` |

The two classic mistakes: pasting your normal Gmail password (won't work —
it must be an App Password), and leaving the spaces in `abcd efgh ijkl mnop`.

---

## STEP 4 — Confirm the whole flow (2 minutes)

1. App → **Get started** → register with a real address.
2. Code arrives → enter it → account created.
   (First message may land in **spam**; mark "Not spam" once.)
3. Wrong code → **"Wrong OTP."**
4. Sign out → **Forgot password?** → code arrives → set a new password →
   sign in with it. Same email system, so once step 1 works, this works.

---

## What changed in the app (so this can't go silent again)

- OTP emails now send **while the request is happening**, so a failure is
  reported instead of disappearing into a background thread.
- The signup screen tells you plainly when the email couldn't be sent,
  instead of leaving you staring at an empty inbox.
- `/health/mail` reports provider, settings presence, and the last error —
  without ever exposing keys or passwords.
- Three providers supported: Resend and Brevo over HTTPS, plus SMTP.
- Fixed: the "Use a different email" link did nothing (the screen was
  already on that route, so nothing re-rendered). It works now.
