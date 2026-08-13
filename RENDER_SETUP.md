# 🚀 Part 4 — Render + Database, from scratch

Follow top to bottom. About 30 minutes. Everything here is free.

---

## ⚠️ STEP 0 — Reset the database password you pasted publicly (2 min)

You shared your Neon connection string in chat, which includes its password.
Anyone who saw it can read or delete your users' data. Rotate it first:

1. Go to https://console.neon.tech → open your project.
2. Left sidebar → **Roles** (or Branches → your branch → Roles).
3. Find `neondb_owner` → **⋯** menu → **Reset password** → confirm.
4. Copy the NEW connection string from **Dashboard → Connect** (choose
   "Connection string", make sure it ends with `?sslmode=require`).
5. Use that new one everywhere below. Never paste it in chat, screenshots,
   or GitHub again — it goes in Render's Environment tab only.

---

## Why a database at all (30-second version)

Render's free web service has a **temporary filesystem**. Every deploy and
every restart wipes it. If your data lived in a file on that machine, every
account, streak and log would silently vanish — the worst kind of bug,
because it looks fine until a user comes back and everything's gone.

Neon is a free Postgres database that lives *outside* Render and keeps data
forever. Your app now supports both: a local file while you develop, real
Postgres in production. It picks automatically based on one setting.

---

## STEP 1 — Get your Neon database URL (5 min)

If you don't have a Neon project yet:

1. https://neon.tech → **Sign up** (GitHub login is fine, free tier, no card).
2. **Create project** → name it `healthbuddy` → region closest to you →
   Create.
3. On the project dashboard click **Connect** → copy the **connection
   string**. It looks like:
   `postgresql://neondb_owner:PASSWORD@ep-something.aws.neon.tech/neondb?sslmode=require`
4. Keep that tab open — you'll paste it into Render in Step 3.

---

## STEP 2 — Create the Render web service (10 min)

1. https://render.com → **Get Started** → sign in **with GitHub**.
2. Dashboard → **New +** → **Web Service**.
3. **Connect a repository** → pick `healthbuddy`. (If it's not listed:
   "Configure account" → grant Render access to that repo.)
4. Fill in the form:

| Field | Value |
|---|---|
| **Name** | `healthbuddy` (this becomes your web address) |
| **Region** | Singapore, or whichever is nearest |
| **Branch** | `main` |
| **Root Directory** | *leave empty* |
| **Runtime / Language** | Python 3 |
| **Build Command** | `pip install -r requirements.txt && python seed.py` |
| **Start Command** | `gunicorn -w 2 -b 0.0.0.0:$PORT "healthbuddy:create_app()"` |
| **Instance Type** | Free |

**Don't click Create yet** — add the settings below first.

---

## STEP 3 — Add the environment variables (5 min)

Still on that page, find **Environment Variables** → **Add** for each row.
(Already created the service? Then: service → **Environment** → Add.)

| Key | Value |
|---|---|
| `HB_DATABASE_URL` | your NEW Neon connection string from Step 1 |
| `HB_SECRET_KEY` | 60+ random characters you make up (keep it secret) |
| `HB_SMTP_HOST` | `smtp.gmail.com` |
| `HB_SMTP_PORT` | `587` |
| `HB_SMTP_USER` | your new HealthBuddy Gmail address |
| `HB_SMTP_PASS` | the 16-character Gmail App Password, no spaces |
| `HB_MAIL_FROM_NAME` | `HealthBuddy` |
| `HB_EXPOSE_RESET_TOKEN` | `0` |

Then click **Create Web Service** (or **Save changes**). First build takes
3–5 minutes. When the log ends with something like
`Booting worker` and the status turns **Live**, you have a link:
`https://healthbuddy-xxxx.onrender.com`

*(No Gmail App Password yet? Set the four SMTP ones later — everything else
works, and OTP codes go to the Render logs meanwhile.)*

---

## STEP 4 — Verify it properly (5 min)

**A. Is the database really connected?**
Open `https://YOUR-LINK.onrender.com/health/db` in a browser. You want:

```json
{"engine": "postgres", "persistent": true, "users": 0, "cards": 60, "ok": true}
```

- `"engine": "postgres"` ✅ your data is safe and permanent.
- `"engine": "sqlite (temporary!)"` ❌ `HB_DATABASE_URL` is missing or
  misspelled — fix it in Environment and redeploy.
- `"cards": 60` means the seed step ran and your nudge content is loaded.

**B. Does signup with OTP work?**
Open the app → **Get started** → register with a real email → check inbox
(and spam the first time) → enter the 6-digit code → account created. Enter
a wrong code first if you want to see **"Wrong OTP."**

**C. Does the password reset work?**
Sign out → **Forgot password?** → enter that email → code arrives → set a
new password → sign in with the new one.

**D. The big one — does data survive a restart?**
This is what the whole database change is for:
1. Log some water in the app.
2. Render dashboard → **Manual Deploy** → **Deploy latest commit**.
3. When it's Live again, sign in with the same email and password.
4. Your account, water log and streak are all still there. ✅
   (Before this change, everything would have been wiped.)

**E. Sign out → sign back in** with the same credentials. Works, because the
password lives in Postgres now, not in a file that disappears.

---

## Everyday notes

- **Free tier sleeps** after ~15 quiet minutes; the next visit takes ~30
  seconds to wake. Your data is untouched — that's just the server yawning.
- **Updating the app:** push to GitHub → Render redeploys itself → users get
  it instantly on the web, and after a fresh APK build for the phone app.
- **Backups:** Neon keeps automatic point-in-time history on the free plan.
  Console → your project → **Backups / History**.
- **Never** put the database URL or `HB_SECRET_KEY` in GitHub. Environment
  variables only.

## If something goes wrong

| What you see | What it means |
|---|---|
| Build fails on `pip install` | Render → Logs → copy the red lines → send to Claude |
| `/health/db` says `sqlite (temporary!)` | `HB_DATABASE_URL` missing/misspelled (case-sensitive) |
| `/health/db` shows `ok: false` with a connection error | Wrong password (did you rotate it?) or the URL lost `?sslmode=require` |
| Site loads but every action fails | Open Logs while tapping in the app; the red traceback names the query |
| No OTP email | Logs → search `[mail]` — see EMAIL_SETUP.md's table |
