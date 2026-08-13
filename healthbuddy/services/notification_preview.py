"""Personalized notification PREVIEW/example engine.

Purpose
-------
Every piece of the always-on notification pipeline already lives in this
codebase (see services/notify.py for the real-time composer, services/
segmentation.py for the cold-start category weighting, services/cycle.py for
Period Care, services/context.py for the live home-screen signals). What was
missing was a lightweight, DB-free layer that turns those same signals into
a handful of READABLE EXAMPLE notifications — useful for:

  1. An onboarding "here's what your notifications will look like" preview
     shown right after the user answers gender / occupation / goals.
  2. Demoing/QAing personalization against a batch of user profiles (e.g. a
     CSV export) without needing a live DB per profile.

This module never touches the database directly — call sites that have a
real user pass in the already-fetched profile + today's stats; the
standalone script scripts/generate_notification_examples.py builds them
from CSV rows instead. The real, always-on delivery pipeline is still
notify.compose() / notify.compose_slot() — this module is the *example*
layer that sits next to it.
"""
from . import segmentation
from . import cycle as cycle_svc

GOAL_LABELS = {
    "fitness": "Get fitter",
    "stress": "Manage stress",
    "sleep": "Sleep better",
    "eat_better": "Eat better",
    "general": "General wellness",
}

# One flagship example per goal — the message a user picking that goal
# should recognize as "yes, this is why I'm here."
GOAL_EXAMPLES = {
    "fitness": ("🏃", "Legs check-in",
                "You picked 'get fitter' — so today's the day we stop admiring the stairs and start using them. 3 flights, right now?"),
    "stress": ("🧘", "60-second reset",
               "You told us stress is the thing to manage. Here's a tiny one: breathe in for 4, hold 4, out for 4. Three rounds. Go."),
    "sleep": ("🌙", "Wind-down window",
              "Sleep better was your goal — screens off in 20 minutes gives your brain a real shot at it tonight."),
    "eat_better": ("🥗", "Plate check",
                   "Eating better starts one meal at a time. What's actually on your plate for lunch today?"),
    "general": ("✨", "Small win o'clock",
                "General wellness = a bunch of small wins stacked up. Pick ANY one thing right now — water, a stretch, a walk."),
}

OCCUPATION_EXAMPLES = {
    "student": ("📚", "Deadline-proof your body",
                "Between classes and deadlines it's easy to skip meals. Quick one — have you eaten in the last 5 hours?"),
    "professional": ("💼", "Desk parole",
                     "You've earned a 5-minute release from that desk. Stand, stretch, refill your water — back to it after."),
}

# Home-screen data → the notification that data justifies. Order matters:
# first matching rule wins so the most urgent/relevant signal is shown.
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


def _period_care_example(gender, period_care_enabled, cycle_phase=None):
    if gender != "female" or not period_care_enabled:
        return None
    if cycle_phase and cycle_phase in cycle_svc.PHASE_NUDGES:
        emoji, title, body = cycle_svc.PHASE_NUDGES[cycle_phase][0]
        return (emoji, title, body)
    # No cycle logged yet — invite them to start tracking instead of guessing.
    return ("🌸", "Period Care is on", "Log your last period start date and we'll start predicting your cycle and phase-aware tips.")


def preview(gender=None, occupation=None, goals=None, stats=None, period_care_enabled=False, cycle_phase=None):
    """Build 3-5 example personalized notifications for a profile.

    gender: 'male' | 'female' | 'nonbinary' | 'prefer_not'
    occupation: 'student' | 'professional' | 'other'
    goals: list of GOAL_LABELS keys, e.g. ['fitness', 'sleep']
    stats: dict of today's home-screen data, any subset of:
           daily_steps, step_goal, screen_time_hours, water_logs_today,
           meal_logs_today, sleep_hours_last_night, mood_streak_days
    """
    goals = [g for g in (goals or []) if g in GOAL_EXAMPLES] or ["general"]
    stats = stats or {}
    examples = []

    # 1) Goal-driven example(s) — the clearest "this app gets me" moment.
    for g in goals[:2]:
        emoji, title, body = GOAL_EXAMPLES[g]
        examples.append({"tag": f"goal:{g}", "emoji": emoji, "title": title, "body": body})

    # 2) Occupation-flavoured example.
    if occupation in OCCUPATION_EXAMPLES:
        emoji, title, body = OCCUPATION_EXAMPLES[occupation]
        examples.append({"tag": f"occupation:{occupation}", "emoji": emoji, "title": title, "body": body})

    # 3) Live home-screen data examples (steps/screen/water/meals/sleep/streak).
    for emoji, title, body in _stat_examples(stats)[:2]:
        examples.append({"tag": "home_data", "emoji": emoji, "title": title, "body": body})

    # 4) Period Care — only ever shown/enabled for gender == female, and only
    #    when the user has opted in, exactly like the real cycle.py gating.
    pc = _period_care_example(gender, period_care_enabled, cycle_phase)
    if pc:
        emoji, title, body = pc
        examples.append({"tag": "period_care", "emoji": emoji, "title": title, "body": body})

    # 5) Show the category weighting driving all of this, for transparency
    #    (mirrors the /api/transparency endpoint's spirit).
    weights = segmentation.compute_weights(goals, occupation, stats.get("activity_level", "moderate"), gender)
    top_category = max(weights, key=weights.get) if weights else None

    return {"examples": examples, "category_weights": weights, "top_category": top_category}
