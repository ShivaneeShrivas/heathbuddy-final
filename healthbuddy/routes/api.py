"""REST API. All endpoints under /api. Errors are friendly, specific,
and actionable (what happened + how to fix)."""
import re
from datetime import date

from flask import Blueprint, current_app, g, jsonify, request

from ..auth import (device_label_from_request, hash_password, issue_refresh_token,
                    issue_token, new_buddy_code, require_auth, revoke_refresh_token,
                    rotate_refresh_token, verify_password, verify_refresh_token)
from ..config import CATEGORIES, CATEGORY_META
from ..db import execute, query
from ..services import (bandit, gamification, notify, notification_preview, nudges, push,
                        scheduler, segmentation, social)

api = Blueprint("api", __name__, url_prefix="/api")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
OCCUPATIONS = {"student", "professional", "other"}
GENDERS = {"female", "male", "nonbinary", "prefer_not"}
ACTIVITY = {"active", "moderate", "inactive"}
GOALS = {"fitness", "stress", "sleep", "eat_better", "general"}
HABITS = {"water", "meal", "sleep", "mood"}


def body():
    return request.get_json(silent=True) or {}


# ---------- Auth ----------

def _send_code(email, purpose, kind_sender):
    """Create a code and actually try to deliver it. The result is reported
    honestly: `email_sent` tells the client whether delivery worked, and the
    reason is logged (and surfaced at /health/mail) when it didn't."""
    from ..services import otp as otp_svc
    code = otp_svc.create(email, purpose)
    delivered, reason = kind_sender(email, code, current_app.logger)
    extra = {"email_sent": bool(delivered)}
    if not delivered:
        current_app.logger.info("[otp] %s code for %s is %s (delivery failed: %s)",
                                purpose, email, code, reason)
        extra["email_error"] = ("We couldn't send the email just now. "
                                "Check /health/mail for the reason.")
        if current_app.config.get("EXPOSE_RESET_TOKEN"):
            extra["dev_code"] = code
    return extra


@api.post("/auth/register")
def register():
    """Step 1 of signup: validate, stash the pending account, email a code.
    No user row exists until the code is confirmed, so unverified emails
    never accumulate in the users table."""
    from ..services import mailer, otp as otp_svc
    data = body()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not name:
        return jsonify(error="Add your name so we know what to call you."), 400
    if not EMAIL_RE.match(email):
        return jsonify(error="That email doesn't look right. Check it and try again."), 400
    if len(password) < 8:
        return jsonify(error="Password needs at least 8 characters."), 400
    if query("SELECT 1 FROM users WHERE email=?", (email,), one=True):
        return jsonify(error="That email already has an account. Try signing in instead."), 409

    execute("""INSERT INTO pending_signups (email, name, password_hash, created_at)
               VALUES (?,?,?,datetime('now'))
               ON CONFLICT(email) DO UPDATE SET name=excluded.name,
                 password_hash=excluded.password_hash, created_at=datetime('now')""",
            (email, name, hash_password(password)))
    try:
        extra = _send_code(email, "verify", mailer.send_verification_code)
    except otp_svc.OtpError as e:
        return jsonify(error=str(e)), 429
    return jsonify(verification_required=True, email=email,
                   message="We've emailed you a 6-digit code. Enter it to finish signing up.",
                   **extra), 200


@api.post("/auth/register/resend")
def register_resend():
    from ..services import mailer, otp as otp_svc
    email = (body().get("email") or "").strip().lower()
    if not query("SELECT 1 FROM pending_signups WHERE email=?", (email,), one=True):
        return jsonify(error="Start signing up again — that request expired."), 400
    try:
        extra = _send_code(email, "verify", mailer.send_verification_code)
    except otp_svc.OtpError as e:
        return jsonify(error=str(e)), 429
    return jsonify(message="New code sent 📬", **extra)


@api.post("/auth/register/verify")
def register_verify():
    """Step 2 of signup: correct code → the account is actually created."""
    from ..services import otp as otp_svc
    data = body()
    email = (data.get("email") or "").strip().lower()
    pending = query("SELECT * FROM pending_signups WHERE email=?", (email,), one=True)
    if pending is None:
        return jsonify(error="Start signing up again — that request expired."), 400
    if query("SELECT 1 FROM users WHERE email=?", (email,), one=True):
        return jsonify(error="That email already has an account. Try signing in instead."), 409
    try:
        otp_svc.verify(email, "verify", data.get("code"))
    except otp_svc.OtpError as e:
        return jsonify(error=str(e)), 400
    user_id = execute(
        """INSERT INTO users (email, password_hash, name, buddy_code, email_verified)
           VALUES (?,?,?,?,1)""",
        (email, pending["password_hash"], pending["name"], new_buddy_code()))
    execute("DELETE FROM pending_signups WHERE email=?", (email,))
    refresh_token = issue_refresh_token(user_id, device_label_from_request())
    return jsonify(token=issue_token(user_id), refresh_token=refresh_token,
                   user=_public_user(user_id)), 201


@api.post("/auth/login")
def login():
    data = body()
    user = query("SELECT * FROM users WHERE email=?",
                 ((data.get("email") or "").strip().lower(),), one=True)
    if user is None or not verify_password(data.get("password") or "", user["password_hash"]):
        return jsonify(error="Email and password don't match. Try again."), 401
    refresh_token = issue_refresh_token(user["id"], device_label_from_request())
    return jsonify(token=issue_token(user["id"]), refresh_token=refresh_token,
                   user=_public_user(user["id"]))


@api.post("/auth/refresh")
def refresh():
    """Trade a still-valid refresh token for a new access token, without the
    user re-entering a password. This is the call the client makes silently
    in the background — it's the whole mechanism behind staying logged in."""
    data = body()
    session = verify_refresh_token(data.get("refresh_token") or "")
    if session is None:
        return jsonify(error="Your session has expired. Sign in again."), 401
    new_refresh = rotate_refresh_token(session, device_label_from_request())
    return jsonify(token=issue_token(session["user_id"]), refresh_token=new_refresh,
                   user=_public_user(session["user_id"]))


@api.post("/auth/logout")
def logout():
    """Revoke this device's refresh token server-side. Safe to call even if
    the access token already expired (that's the whole point of logout)."""
    data = body()
    revoke_refresh_token(data.get("refresh_token") or "")
    return jsonify(ok=True)


@api.post("/auth/forgot-password")
def forgot_password():
    """Emails a 6-digit reset code. Always answers with the same generic
    message so the endpoint can't be used to discover which emails are
    registered."""
    from ..services import mailer, otp as otp_svc
    email = (body().get("email") or "").strip().lower()
    generic = {"message": "If an account exists for that email, we've sent a reset code."}
    user = query("SELECT * FROM users WHERE email=?", (email,), one=True)
    if user is None:
        return jsonify(**generic)
    try:
        extra = _send_code(email, "reset", mailer.send_reset_code)
    except otp_svc.OtpError as e:
        return jsonify(error=str(e)), 429
    return jsonify(**generic, **extra)


@api.post("/auth/reset-password")
def reset_password():
    """Sets a new password using the emailed code (legacy link tokens still
    accepted). Every existing session is revoked, so a stolen device can't
    stay signed in past a reset."""
    from ..services import email as email_svc, otp as otp_svc
    data = body()
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    token = data.get("token") or ""
    new_password = data.get("password") or ""
    if len(new_password) < 8:
        return jsonify(error="Password must be at least 8 characters."), 400

    if code:
        user = query("SELECT * FROM users WHERE email=?", (email,), one=True)
        if user is None:
            return jsonify(error="Wrong OTP."), 400
        try:
            otp_svc.verify(email, "reset", code)
        except otp_svc.OtpError as e:
            return jsonify(error=str(e)), 400
        user_id = user["id"]
    else:
        user_id = email_svc.consume_reset_token(token)
        if user_id is None:
            return jsonify(error="That reset code is invalid or has expired. Request a new one."), 400

    execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), user_id))
    execute("UPDATE sessions SET revoked_at=datetime('now') WHERE user_id=? AND revoked_at IS NULL",
            (user_id,))
    return jsonify(ok=True, message="Password updated. Sign in with your new one.")


def _public_user(user_id):
    u = query("SELECT * FROM users WHERE id=?", (user_id,), one=True)
    return {"id": u["id"], "name": u["name"], "email": u["email"],
            "buddy_code": u["buddy_code"], "onboarded": bool(u["onboarded"]),
            "occupation": u["occupation"], "gender": u["gender"],
            "activity_level": u["activity_level"], "health_goal": u["health_goal"],
            "quiet_start": u["quiet_start"], "quiet_end": u["quiet_end"]}


@api.get("/me")
@require_auth
def me():
    return jsonify(user=_public_user(g.user["id"]))


# ---------- Onboarding → segmentation → bandit priors ----------

@api.post("/onboarding")
@require_auth
def onboarding():
    data = body()
    occupation, gender = data.get("occupation"), data.get("gender")
    activity = data.get("activity_level")
    goals = data.get("health_goals") or ([data.get("health_goal")] if data.get("health_goal") else [])
    goals = [str(x).strip() for x in goals if x]
    goal = goals[0] if goals else None
    problems = []
    if occupation not in OCCUPATIONS:
        problems.append("occupation must be one of: " + ", ".join(sorted(OCCUPATIONS)))
    if gender not in GENDERS:
        problems.append("gender must be one of: " + ", ".join(sorted(GENDERS)))
    if activity not in ACTIVITY:
        problems.append("activity_level must be one of: " + ", ".join(sorted(ACTIVITY)))
    if not goals or any(x not in GOALS for x in goals):
        problems.append("health_goal(s) must be from: " + ", ".join(sorted(GOALS)))
    if problems:
        return jsonify(error="; ".join(problems)), 400

    first_time = not g.user["onboarded"]
    execute("UPDATE users SET occupation=?, gender=?, activity_level=?, health_goal=?, health_goals=?, onboarded=1 WHERE id=?",
            (occupation, gender, activity, goal, ",".join(goals), g.user["id"]))
    weights = segmentation.compute_weights(goals, occupation, activity, gender)
    bandit.seed_priors(g.user["id"], weights)
    xp = gamification.award_xp(g.user["id"], "onboarding") if first_time else 0
    if first_time:
        execute("INSERT OR IGNORE INTO user_badges (user_id, badge_code) VALUES (?, 'first_steps')",
                (g.user["id"],))
    return jsonify(weights=weights, xp_earned=xp, user=_public_user(g.user["id"]))


@api.post("/onboarding/preview")
@require_auth
def onboarding_preview():
    """'Here's what your notifications will look like' — shown on the last
    onboarding screen, built from the answers the user just picked (not yet
    saved) plus whatever real home-screen data already exists for them today.
    Doesn't require onboarded=1, unlike /nudges/next."""
    data = body()
    occupation, gender = data.get("occupation"), data.get("gender")
    goals = data.get("health_goals") or ([data.get("health_goal")] if data.get("health_goal") else [])
    goals = [str(x).strip() for x in goals if x]
    period_care_enabled = bool(data.get("period_care_enabled")) and gender == "female"

    from . import context as context_svc  # local import avoids a cycle at module load
    ctx = context_svc.build(g.user["id"])
    stats = {}
    if ctx:
        stats = {
            "daily_steps": ctx["steps"],
            "step_goal": ctx["profile"]["step_goal"],
            "screen_time_hours": (ctx["screen_minutes"] / 60) if ctx["screen_minutes"] is not None else None,
            "water_logs_today": ctx["today"]["water_glasses"],
            "meal_logs_today": ctx["today"]["meals"],
            "sleep_hours_last_night": ctx["today"]["sleep_hours"],
            "mood_streak_days": gamification.streak(g.user["id"], "mood"),
            "activity_level": data.get("activity_level"),
        }
    cycle_phase = None
    if period_care_enabled:
        try:
            from . import cycle as cycle_svc
            cycle_phase = cycle_svc.status(g.user["id"]).get("phase")
        except LookupError:
            pass

    result = notification_preview.preview(
        gender=gender, occupation=occupation, goals=goals, stats=stats,
        period_care_enabled=period_care_enabled, cycle_phase=cycle_phase,
    )
    return jsonify(result)


# ---------- Nudges ----------

@api.get("/nudges/next")
@require_auth
def next_nudge():
    if not g.user["onboarded"]:
        return jsonify(error="Finish onboarding first so nudges can be tuned to you."), 409
    card = nudges.next_nudge(g.user["id"], g.user["gender"])
    if card is None:
        return jsonify(error="The content bank is empty. Run the seed script."), 503
    return jsonify(nudge=card)


@api.post("/nudges/<int:card_id>/interact")
@require_auth
def interact(card_id):
    action = body().get("action")
    try:
        result = nudges.interact(g.user["id"], card_id, action)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except LookupError:
        return jsonify(error="That nudge doesn't exist."), 404
    return jsonify(**result)


@api.get("/nudges/feed")
@require_auth
def feed():
    return jsonify(feed=nudges.feed(g.user["id"]))


# ---------- Tracking & dashboard ----------

@api.post("/logs")
@require_auth
def add_log():
    data = body()
    habit = data.get("type")
    if habit not in HABITS:
        return jsonify(error="type must be one of: " + ", ".join(sorted(HABITS))), 400
    try:
        value = float(data.get("value", 1))
    except (TypeError, ValueError):
        return jsonify(error="value must be a number."), 400
    if habit == "sleep" and not (0 < value <= 24):
        return jsonify(error="Sleep hours should be between 0 and 24."), 400
    if habit == "mood" and not (1 <= value <= 5):
        return jsonify(error="Mood is a 1–5 scale."), 400
    execute("INSERT INTO habit_logs (user_id, type, value, note) VALUES (?,?,?,?)",
            (g.user["id"], habit, value, (data.get("note") or "")[:280]))
    xp = gamification.award_xp(g.user["id"], "habit_log")
    new_badges = gamification.check_and_award(g.user["id"])
    return jsonify(xp_earned=xp, new_badges=new_badges,
                   streak=gamification.streak(g.user["id"], habit)), 201


@api.get("/dashboard")
@require_auth
def dashboard():
    score = nudges.health_score(g.user["id"])
    prof = gamification.profile(g.user["id"])
    return jsonify(greeting_name=g.user["name"].split()[0],
                   score=score, streaks=prof["streaks"],
                   level=prof["level"], xp=prof["xp"],
                   level_progress=prof["progress"], next_at=prof["next_at"])


@api.get("/history/<habit>")
@require_auth
def history(habit):
    if habit not in HABITS:
        return jsonify(error="Unknown habit type."), 400
    rows = query("SELECT logged_on, COUNT(*) AS count, SUM(value) AS total FROM habit_logs "
                 "WHERE user_id=? AND type=? GROUP BY logged_on ORDER BY logged_on DESC LIMIT 30",
                 (g.user["id"], habit))
    return jsonify(history=[dict(r) for r in rows])


# ---------- Knowledge hub ----------

@api.get("/cards")
@require_auth
def cards():
    category = request.args.get("category")
    if category and category not in CATEGORIES:
        return jsonify(error="Unknown category."), 400
    sql = "SELECT * FROM notification_cards WHERE audience IN ('all', ?)"
    args = [g.user["gender"] or "all"]
    if category:
        sql += " AND category=?"
        args.append(category)
    rows = query(sql + " ORDER BY category, id", args)
    return jsonify(cards=[nudges.card_dict(r) for r in rows],
                   categories=[{"key": c, **CATEGORY_META[c]} for c in CATEGORIES])


@api.get("/cards/daily")
@require_auth
def card_of_day():
    rows = query("SELECT * FROM notification_cards WHERE deep_dive IS NOT NULL ORDER BY id")
    if not rows:
        return jsonify(error="No content yet."), 503
    pick = rows[date.today().toordinal() % len(rows)]
    return jsonify(card=nudges.card_dict(pick))


# ---------- Gamification, transparency, preferences ----------

@api.get("/gamification/profile")
@require_auth
def gamification_profile():
    return jsonify(**gamification.profile(g.user["id"]))


@api.get("/transparency")
@require_auth
def transparency():
    return jsonify(
        explanation=("Your nudges are picked by a learning system. It started from your "
                     "onboarding answers and updates every time you act on, open, snooze, "
                     "or dismiss a nudge. Higher affinity means you'll see that category more."),
        state=[{**s, **{"label": CATEGORY_META[s["category"]]["label"],
                        "emoji": CATEGORY_META[s["category"]]["emoji"],
                        "color": CATEGORY_META[s["category"]]["color"]}}
               for s in bandit.get_state(g.user["id"])])


@api.patch("/preferences")
@require_auth
def preferences():
    data = body()
    for cat, mult in (data.get("category_weights") or {}).items():
        if cat in CATEGORIES:
            bandit.set_preference(g.user["id"], cat, mult)
    updates, args = [], []
    for field in ("quiet_start", "quiet_end"):
        if field in data and re.match(r"^\d{2}:\d{2}$", str(data[field])):
            updates.append(f"{field}=?")
            args.append(data[field])
    if updates:
        execute(f"UPDATE users SET {', '.join(updates)} WHERE id=?", (*args, g.user["id"]))
    return jsonify(ok=True, user=_public_user(g.user["id"]))


# ---------- Social ----------

@api.get("/challenges")
@require_auth
def challenges():
    return jsonify(challenges=social.list_challenges(g.user["id"]))


@api.post("/challenges/<int:challenge_id>/join")
@require_auth
def join_challenge(challenge_id):
    try:
        return jsonify(**social.join(g.user["id"], challenge_id))
    except LookupError:
        return jsonify(error="That challenge doesn't exist."), 404


@api.get("/challenges/<int:challenge_id>/leaderboard")
@require_auth
def challenge_leaderboard(challenge_id):
    try:
        return jsonify(**social.leaderboard(challenge_id))
    except LookupError:
        return jsonify(error="That challenge doesn't exist."), 404


@api.post("/buddies/link")
@require_auth
def link_buddy():
    try:
        return jsonify(**social.link_buddy(g.user["id"], body().get("code") or ""))
    except LookupError as e:
        return jsonify(error=str(e)), 404
    except ValueError as e:
        return jsonify(error=str(e)), 400


@api.get("/buddies")
@require_auth
def buddies():
    return jsonify(buddies=social.list_buddies(g.user["id"]), my_code=g.user["buddy_code"])


# ---------- Push notifications (real phone push, works app-closed) ----------

@api.get("/push/public-key")
def push_public_key():
    """No auth needed - this is not a secret, the frontend needs it before
    the user even logs in isn't required here, but keeping it open avoids
    a chicken-and-egg race with token timing on first load."""
    key = current_app.config["VAPID_PUBLIC_KEY"]
    if not key:
        return jsonify(error="Push isn't configured on this server yet."), 503
    return jsonify(public_key=key)


@api.post("/push/subscribe")
@require_auth
def push_subscribe():
    data = body()
    sub = data.get("subscription")
    if not sub or not sub.get("endpoint") or not sub.get("keys"):
        return jsonify(error="Missing subscription details."), 400
    push.save_subscription(g.user["id"], sub, request.headers.get("User-Agent"))
    return jsonify(ok=True)


@api.post("/push/unsubscribe")
@require_auth
def push_unsubscribe():
    endpoint = body().get("endpoint")
    if endpoint:
        push.remove_subscription(endpoint)
    return jsonify(ok=True)


@api.post("/push/test")
@require_auth
def push_test():
    """Manual trigger so you can confirm delivery works end-to-end (including
    with the app fully closed) without waiting for the background worker."""
    picks = notify.compose(g.user["id"], limit=1)
    if not picks:
        payload = {"title": "HealthBuddy", "body": "Test push - if you can see this, it's working! 🎉",
                   "emoji": "✅", "url": "/#home"}
    else:
        p = picks[0]
        payload = {"title": f"{p['emoji']} {p['title']}", "body": p["body"], "url": "/#nudges"}
    sent = push.send_to_user(g.user["id"], payload)
    if sent == 0:
        return jsonify(error="No active subscription found - enable notifications first."), 404
    return jsonify(ok=True, sent_to=sent)


@api.post("/push/snooze")
def push_snooze():
    """'Remind in 1h' button on the system notification. No @require_auth -
    a service worker has no JWT to attach - authenticity comes from the
    HMAC signature embedded in the original push payload instead."""
    data = body()
    user_id, template_id, sig = data.get("user_id"), data.get("template_id"), data.get("sig")
    if not push.verify_action(user_id, template_id, sig):
        return jsonify(error="Invalid or expired action."), 403
    notify.snooze(user_id, template_id, minutes=60)
    return jsonify(ok=True)


@api.post("/push/ack")
def push_ack():
    """'Done' button on the system notification - same auth approach as
    /push/snooze. Awards a small XP nudge for responding directly from the
    notification, without needing the app open."""
    data = body()
    user_id, template_id, sig = data.get("user_id"), data.get("template_id"), data.get("sig")
    if not push.verify_action(user_id, template_id, sig):
        return jsonify(error="Invalid or expired action."), 403
    execute("INSERT INTO xp_events (user_id, amount, reason) VALUES (?,?,?)",
            (user_id, 5, f"push_ack:{template_id}"))
    return jsonify(ok=True)


@api.post("/push/run-tick")
def push_run_tick():
    """Runs one scheduling pass (due slots + due snoozes) over HTTP, so a
    free external cron pinger (cron-job.org, GitHub Actions schedule, etc)
    can drive notifications without paying for a Render background worker.
    Protected by a shared secret since it has no user session - set
    HB_TICK_SECRET and pass it as ?token=... or the X-Tick-Token header."""
    configured = current_app.config.get("TICK_SECRET")
    if not configured:
        return jsonify(error="HB_TICK_SECRET is not set on the server."), 503
    supplied = request.args.get("token") or request.headers.get("X-Tick-Token")
    if not supplied or supplied != configured:
        return jsonify(error="Invalid token."), 403
    result = scheduler.run_tick_once()
    return jsonify(result)
