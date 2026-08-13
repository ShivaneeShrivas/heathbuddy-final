# ✅ DO THIS NOW — final setup (25 minutes, ₹0)

Everything is built and tested. Only ONE thing is left that needs you:
switching email to a provider that delivers to **everyone**, not just you.

---

## Why we're switching (10-second version)

| | Gmail SMTP | Resend | **Brevo** |
|---|---|---|---|
| Works on Render | ❌ blocked | ✅ | ✅ |
| Sends to ANY user | ✅ | ❌ only you, unless you buy a domain | ✅ |
| Cost | free | free | **free — 300/day forever** |

Brevo is the only free option that does both. Your app already supports it —
it just needs a key.

---

## PART 1 — Brevo email for all users (10 min)

**Step 1.** Go to **https://www.brevo.com** → **Sign up free**
(no credit card). Use your `apphealthbuddy@gmail.com` account.

**Step 2.** Confirm the signup email Brevo sends you, and finish the short
questionnaire (pick anything — "I'm a developer" is fine).

**Step 3. Verify your sender address.** In Brevo:
→ click your name (top right) → **Senders, Domains & Dedicated IPs**
→ **Senders** tab → **Add a sender**
→ Name: `HealthBuddy`, Email: `apphealthbuddy@gmail.com` → **Save**
→ open the confirmation email Brevo sends and click the link.
*(You do NOT need a domain. This one verified address is enough.)*

**Step 4. Get the API key.** Click your name (top right) → **SMTP & API**
→ **API keys** tab → **Generate a new API key** → name it `healthbuddy`
→ copy the key (starts with `xkeysib-`). It's shown once.

**Step 5. Put it in Render.** Render dashboard → your service →
**Environment** → add/edit these two:

| Key | Value |
|---|---|
| `HB_BREVO_API_KEY` | the `xkeysib-...` key |
| `HB_MAIL_FROM` | `apphealthbuddy@gmail.com` (the address you just verified) |

Then **delete** `HB_RESEND_API_KEY` (click the 🗑️ next to it) so the app
uses Brevo. Leave the `HB_SMTP_*` ones — harmless.

**Step 6. Save changes.** Render restarts on its own (~1 min).

---

## PART 2 — Upload the new code (5 min)

1. Unzip the newest `healthbuddy.zip`.
2. GitHub → your `healthbuddy` repo → **Add file → Upload files** →
   select everything inside the folder (Ctrl+A) → drag in → **Commit**.
3. Render redeploys automatically. *(If it doesn't: Manual Deploy → Deploy
   latest commit. And turn on Settings → Auto-Deploy → Yes.)*

---

## PART 3 — Verify (5 min) — do these in order

Replace `YOUR-APP` with `healthbuddy-1-xthv`.

**1. Right code is live**
`https://YOUR-APP.onrender.com/health`
→ expect `"build": "2026-08-04-final"`

**2. Database is permanent**
`https://YOUR-APP.onrender.com/health/db`
→ expect `"engine": "postgres"`, `"persistent": true`, `"cards": 60`

**3. Email reaches a NON-you address** ← the important one
`https://YOUR-APP.onrender.com/health/mail?to=A-FRIENDS-EMAIL`
→ expect `"provider": "brevo"` and `"ok": true`
→ your friend should receive "HealthBuddy test email" (check spam once)

**4. Real signup** — open the app, register with any email, code arrives,
enter it, you're in. Wrong code → **"Wrong OTP."**

**5. Forgot password** — sign out → Forgot password? → code arrives →
new password → sign in with it.

**6. Data survives** — log some water → Render → Manual Deploy → when Live,
sign in again → water still logged, streak intact. ✅

**7. Theme** — Profile → Appearance → ☀️ Light / 🌙 Dark.

**8. Buddy** — log water and watch it drink; log a meal and it eats; open the
app after 10pm and it's sleepy.

---

## PART 4 — New APK for steps & screen time (10 min, optional today)

The web version can't read phone sensors (browser rule). For that:

1. GitHub → `native/capacitor.config.json` → make sure the URL is your real
   Render link.
2. **Actions** tab → **Build Android APK** → **Run workflow** → wait for the
   green tick → **Artifacts** → download → uninstall the old app → install.
3. Profile → Data & Permissions → **Connect** on Steps → Allow → walk
   around → the number climbs by itself.

---

## What's in this build

- **Email:** Brevo / Resend / SMTP supported; OTP verification for signup,
  emailed reset codes for forgotten passwords; `/health/mail` explains any
  failure in plain English.
- **Database:** Postgres (Neon) so nothing is ever wiped by a restart;
  automatic, safe migrations; SQLite still used for local development.
- **Login:** refresh tokens + sessions, so signing out and back in with the
  same credentials always works; a password reset revokes old sessions.
- **Buddy:** your artwork, 8 poses, reacting to water/meal/sleep/mood, time
  of day, score, and streaks — inside the glowing ring from your logo.
- **Themes:** dark and light, remembered per device.
- **Steps & screen time:** untouched and re-verified — native Android
  plugins, permission flow, 15-minute auto-sync, home cards.
- **Safety net:** 54 automated tests, run against BOTH SQLite and Postgres,
  plus a headless check that renders all 16 screens to catch missing code
  before it ships.

## If anything looks wrong

Open `/health`, `/health/db`, `/health/mail` — between them they tell you
which layer is unhappy. Paste the output (or the red text from Render →
Logs) and it can be fixed quickly.
