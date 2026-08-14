"""Personalized notification PREVIEW/example engine.

Purpose
-------
Every piece of the always-on notification pipeline already lives in this
codebase (see services/notify.py for the real-time composer, services/
segmentation.py for the cold-start category weighting, services/cycle.py for
Period Care, services/context.py for the live home-screen signals). What was
missing was a lightweight, DB-free layer that turns those same signals into
a READABLE SET of example notifications — useful for:

  1. An onboarding "here's what your notifications will look like" preview
     shown right after the user answers gender / occupation / goals.
  2. The native app's actual daily local-notification schedule (see
     enableLocalNotifs() in app.js) — it calls this same engine so what's
     previewed during onboarding is what actually fires later.
  3. Demoing/QAing personalization against a batch of user profiles (e.g. a
     CSV export) without needing a live DB per profile.

This module never touches the database directly — call sites that have a
real user pass in the already-fetched profile + today's stats; the
standalone script scripts/generate_notification_examples.py builds them
from CSV rows instead. The real, always-on server-push delivery pipeline is
still notify.compose() / notify.compose_slot() — this module is the
*example* layer that sits next to it (and, for the native app, the layer
that decides what the on-device schedule actually says).
"""
from . import segmentation
from . import cycle as cycle_svc

# Hard ceiling on how many notifications a day this engine will ever hand
# back, regardless of how many goals/signals a profile matches. Past this,
# a "personalized" health app starts reading as spam and gets its
# notification permission revoked — 10-12/day is already generous for a
# wellness app; most users will want fewer via Profile settings.
MAX_DAILY_NOTIFICATIONS = 12
DEFAULT_DAILY_NOTIFICATIONS = 12

GOAL_LABELS = {
    "fitness": "Get fitter",
    "stress": "Manage stress",
    "sleep": "Sleep better",
    "eat_better": "Eat better",
    "general": "General wellness",
}

# 3 variants per goal so a 10-12/day schedule doesn't repeat the same line
# for both goals. (emoji, title, body)
GOAL_EXAMPLES = {
    "fitness": [
        ("🏃", "Legs check-in",
         "You picked 'get fitter' — so today's the day we stop admiring the stairs and start using them. 3 flights, right now?"),
        ("💪", "Micro workout", "90 seconds: 10 squats, 10 push-ups (knees are fine), 20-sec plank. That's it. Go."),
        ("🚴", "Move break", "Getting fitter isn't one big workout — it's a dozen small ones. This is one of them."),
    ],
    "stress": [
        ("🧘", "60-second reset",
         "You told us stress is the thing to manage. Here's a tiny one: breathe in for 4, hold 4, out for 4. Three rounds. Go."),
        ("🌬️", "Shoulders down", "Quick check — are your shoulders up by your ears right now? Drop them. Unclench your jaw too."),
        ("📵", "5-minute unplug", "Managing stress starts with noticing it. Put the phone down for 5 minutes after this one."),
    ],
    "sleep": [
        ("🌙", "Wind-down window",
         "Sleep better was your goal — screens off in 20 minutes gives your brain a real shot at it tonight."),
        ("☕", "Caffeine cutoff", "If sleep's the goal, this is your reminder: no more caffeine for the rest of today."),
        ("🛏️", "Same time tonight?", "Consistent sleep and wake times matter more than total hours. What time are you aiming for tonight?"),
    ],
    "eat_better": [
        ("🥗", "Plate check",
         "Eating better starts one meal at a time. What's actually on your plate for lunch today?"),
        ("🍎", "Snack swap", "Reaching for a snack? A piece of fruit or a handful of nuts beats the vending machine."),
        ("🍽️", "Slow down", "Eating better isn't just what — it's how. Try eating this next meal without a screen in front of you."),
    ],
    "general": [
        ("✨", "Small win o'clock",
         "General wellness = a bunch of small wins stacked up. Pick ANY one thing right now — water, a stretch, a walk."),
        ("🌤️", "Check-in", "No agenda here — just a nudge to notice how you're doing right now."),
        ("🙂", "One good thing", "What's one small thing you can do for yourself in the next 10 minutes?"),
    ],
}

OCCUPATION_EXAMPLES = {
    "student": [
        ("📚", "Deadline-proof your body",
         "Between classes and deadlines it's easy to skip meals. Quick one — have you eaten in the last 5 hours?"),
        ("🎒", "Backpack break", "Long day of classes? Stand up, stretch your back, roll your shoulders before the next one."),
        ("📖", "Study-break reminder", "Pomodoro's up — this is your built-in excuse to get up and move for 5 minutes."),
    ],
    "professional": [
        ("💼", "Desk parole",
         "You've earned a 5-minute release from that desk. Stand, stretch, refill your water — back to it after."),
        ("🖥️", "20-20-20", "Staring at a screen? Every 20 min, look at something 20 feet away for 20 seconds. Now's a good time."),
        ("☕", "Meeting gap check", "Between meetings — water, stretch, or just breathe. Pick one before the next one starts."),
    ],
}

# Used only to pad out a schedule when the goal/occupation/stat/period pools
# run dry before reaching the user's requested count — keeps a 12/day
# schedule from going quiet mid-afternoon for a low-data new user.
FILLER_EXAMPLES = [
    ("💧", "Sip check", "Quick one — when did you last have water? Might be time for a glass."),
    ("🧍", "Posture ping", "How's your posture right now, this second? Small adjustment, do it now."),
    ("😊", "Mood check", "No wrong answer — how are you actually feeling right now?"),
    ("🌿", "Fresh air", "If you can, step outside for 2 minutes. Free, easy, works."),
    ("🎯", "Streak check", "How's today going against yesterday? No pressure — just checking in."),
    ("🫶", "Be a little kind to yourself", "Whatever today's been like, that's allowed. Small reset, then carry on."),
]


# Home-screen data → the notifications that data justifies. Every item that
# matches is included (not just the first) since these feed a round-robin
# across up to MAX_DAILY_NOTIFICATIONS slots, not a top-3 list.
def _stat_examples(stats):
    out = []
    steps = stats.get("daily_steps")
    goal_steps = stats.get("step_goal", 8000)
    screen_h = stats.get("screen_time_hours")
    water = stats.get("water_logs_today")
    meals = stats.get("meal_logs_today")
    sleep_h = stats.get("sleep_hours_last_night")
    mood_streak = stats.get("mood_streak_days")

    if steps is not None and steps < goal_steps * 0.4:
        out.append(("👀", "Quiet day for your feet",
                     f"Only {steps} steps so far, {goal_steps} is the goal. A 10-minute walk closes a lot of that gap."))
    elif steps is not None and goal_steps * 0.8 <= steps < goal_steps:
        out.append(("🚶", "So close!", f"{steps}/{goal_steps} steps — a short walk finishes the job today."))
    elif steps is not None and steps >= goal_steps:
        out.append(("🔥", "Goal smashed", f"{steps} steps logged — your legs definitely showed up today."))

    if screen_h is not None and screen_h >= 4:
        out.append(("😄", "Attention check",
                     f"{screen_h}h of screen time already. Look away, stretch, blink a few times on purpose."))

    if water is not None and water < 4:
        out.append(("💧", "Hydration check",
                     f"Only {water} glasses logged today — top up before evening catches you dehydrated."))

    if meals is not None and meals < 2:
        out.append(("🍳", "Meal check",
                     f"Just {meals} meal(s) logged today. Don't let the day run away without eating properly."))

    if sleep_h is not None and sleep_h < 6.5:
        out.append(("😴", "Rough night?",
                     f"{sleep_h}h of sleep logged — go easy on yourself today, and try to wind down earlier tonight."))

    if mood_streak is not None and mood_streak >= 3:
        out.append(("🔥", "Mood streak!",
                     f"{mood_streak}-day mood-logging streak. Small consistent habits are the whole game — keep it up."))
    return out


def _period_care_examples(gender, period_care_enabled, cycle_phase=None):
    if gender != "female" or not period_care_enabled:
        return []
    if cycle_phase and cycle_phase in cycle_svc.PHASE_NUDGES:
        # Cap at 2 even if a phase has more variants — Period Care should
        # season the day's notifications, not dominate them.
        return list(cycle_svc.PHASE_NUDGES[cycle_phase][:2])
    # No cycle logged yet — invite them to start tracking instead of guessing.
    return [("🌸", "Period Care is on",
              "Log your last period start date and we'll start predicting your cycle and phase-aware tips.")]


def _tag(tag, items):
    return [{"tag": tag, "emoji": e, "title": t, "body": b} for (e, t, b) in items]


def preview(gender=None, occupation=None, goals=None, stats=None, period_care_enabled=False,
            cycle_phase=None, count=DEFAULT_DAILY_NOTIFICATIONS):
    """Build up to `count` (hard-capped at MAX_DAILY_NOTIFICATIONS) example
    personalized notifications for a profile, interleaved across categories
    so a 10-12/day schedule reads as varied rather than repetitive.

    gender: 'male' | 'female' | 'nonbinary' | 'prefer_not'
    occupation: 'student' | 'professional' | 'other'
    goals: list of GOAL_LABELS keys, e.g. ['fitness', 'sleep']
    stats: dict of today's home-screen data, any subset of:
           daily_steps, step_goal, screen_time_hours, water_logs_today,
           meal_logs_today, sleep_hours_last_night, mood_streak_days
    count: how many notifications to build today (default and hard cap: 12)
    """
    goals = [g for g in (goals or []) if g in GOAL_EXAMPLES] or ["general"]
    stats = stats or {}
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = DEFAULT_DAILY_NOTIFICATIONS
    count = max(1, min(count, MAX_DAILY_NOTIFICATIONS))

    # One bucket per category. Round-robin below pulls one item per bucket
    # per pass, so goal/occupation/home-data/period_care all get seeded
    # into the day early rather than front-loading one category.
    buckets = []
    for g in goals[:2]:
        buckets.append(_tag(f"goal:{g}", GOAL_EXAMPLES.get(g, [])))
    if occupation in OCCUPATION_EXAMPLES:
        buckets.append(_tag(f"occupation:{occupation}", OCCUPATION_EXAMPLES[occupation]))
    buckets.append(_tag("home_data", _stat_examples(stats)))
    pc_examples = _period_care_examples(gender, period_care_enabled, cycle_phase)
    if pc_examples:
        buckets.append(_tag("period_care", pc_examples))
    buckets.append(_tag("wellness", FILLER_EXAMPLES))  # padding, pulled last-priority

    # Round-robin merge across buckets (goal/occupation/period_care first
    # since they're earlier in `buckets`; filler only kicks in once the
    # more personal buckets run dry).
    examples = []
    cursors = [0] * len(buckets)
    while len(examples) < count:
        progressed = False
        for i, bucket in enumerate(buckets):
            if len(examples) >= count:
                break
            if cursors[i] < len(bucket):
                examples.append(bucket[cursors[i]])
                cursors[i] += 1
                progressed = True
        if not progressed:
            break  # every bucket exhausted — fewer than `count` is fine, never fabricate content

    # Category weighting, for transparency (mirrors the /api/transparency
    # endpoint's spirit) — unrelated to which examples were picked above.
    weights = segmentation.compute_weights(goals, occupation, stats.get("activity_level", "moderate"), gender)
    top_category = max(weights, key=weights.get) if weights else None

    return {"examples": examples, "category_weights": weights, "top_category": top_category,
            "count_requested": count, "count_available": len(examples)}
