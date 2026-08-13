"""Generate personalized notification examples for a batch of user profiles.

Usage:
    python scripts/generate_notification_examples.py path/to/profiles.csv [out.csv]

Reads a CSV with columns:
    gender, occupation, primary_goal, secondary_goal, period_care_enabled,
    daily_steps, screen_time_hours, water_logs_today, meal_logs_today,
    sleep_hours_last_night, mood_streak_days, activity_level
(extra columns are ignored — user_id, mood_score, notification_opt_in,
best_notification_time etc. are fine to leave in the file.)

For each row it calls the SAME engine used by POST /api/onboarding/preview
(healthbuddy/services/notification_preview.py, which itself reuses
services/segmentation.py's category weighting) and writes out 3-5 example
notification lines per user — no Flask app, no database required.
"""
import csv
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from healthbuddy.services import notification_preview  # noqa: E402

GOAL_MAP = {
    "get fitter": "fitness",
    "manage stress": "stress",
    "sleep better": "sleep",
    "eat better": "eat_better",
    "general wellness": "general",
}
GENDER_MAP = {"male": "male", "female": "female", "nonbinary": "nonbinary"}
OCC_MAP = {"student": "student", "professional": "professional"}


def _f(row, key):
    v = row.get(key, "")
    try:
        return float(v) if v not in ("", None) else None
    except ValueError:
        return None


def row_to_profile(row):
    goals = [GOAL_MAP.get((row.get("primary_goal") or "").strip().lower())]
    sec = GOAL_MAP.get((row.get("secondary_goal") or "").strip().lower())
    if sec:
        goals.append(sec)
    goals = [g for g in goals if g]

    stats = {
        "daily_steps": int(_f(row, "daily_steps")) if _f(row, "daily_steps") is not None else None,
        "step_goal": 8000,
        "screen_time_hours": _f(row, "screen_time_hours"),
        "water_logs_today": int(_f(row, "water_logs_today")) if _f(row, "water_logs_today") is not None else None,
        "meal_logs_today": int(_f(row, "meal_logs_today")) if _f(row, "meal_logs_today") is not None else None,
        "sleep_hours_last_night": _f(row, "sleep_hours_last_night"),
        "mood_streak_days": int(_f(row, "mood_streak_days")) if _f(row, "mood_streak_days") is not None else None,
        "activity_level": (row.get("activity_level") or "moderate").strip().lower(),
    }
    gender = GENDER_MAP.get((row.get("gender") or "").strip().lower(), "prefer_not")
    occupation = OCC_MAP.get((row.get("occupation") or "").strip().lower(), "other")
    period_care_enabled = (row.get("period_care_enabled") or "").strip().lower() in ("yes", "true", "1")

    return dict(gender=gender, occupation=occupation, goals=goals, stats=stats,
                period_care_enabled=period_care_enabled)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    in_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else "notification_examples_output.csv"

    with open(in_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    out_rows = []
    for row in rows:
        profile = row_to_profile(row)
        result = notification_preview.preview(**profile)
        for ex in result["examples"]:
            out_rows.append({
                "user_id": row.get("user_id", ""),
                "gender": row.get("gender", ""),
                "occupation": row.get("occupation", ""),
                "primary_goal": row.get("primary_goal", ""),
                "notif_type": ex["tag"],
                "emoji": ex["emoji"],
                "title": ex["title"],
                "body": ex["body"],
                "top_category": result["top_category"],
            })

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"{len(rows)} profiles -> {len(out_rows)} example notifications written to {out_path}")
    # Print the first 3 profiles' examples inline as a sanity check.
    for row in rows[:3]:
        profile = row_to_profile(row)
        result = notification_preview.preview(**profile)
        print(f"\n=== {row.get('user_id')} · {row.get('gender')} · {row.get('occupation')} · "
              f"goal={row.get('primary_goal')} ===")
        for ex in result["examples"]:
            print(f"  [{ex['tag']}] {ex['emoji']} {ex['title']} — {ex['body']}")


if __name__ == "__main__":
    main()
