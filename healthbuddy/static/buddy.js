/* HealthBuddy buddy.js — the character companion on the dashboard.
   =========================================================================
   The buddy is real artwork (static/buddy/*.png) shown inside the glowing
   orange ring from the app logo. Which pose appears is a pure function of:

       1. a recent action  (just logged water → drinking, meal → eating…)
       2. the time of day  (early = yawn/stretch/coffee, late = sleepy)
       3. today's score    (high = ready-for-the-day)
       4. the last mood    (great = ready, low = comforting coffee)

   Action poses win for a few seconds, then it settles back to the ambient
   pose — so logging always produces a visible, satisfying reaction.
   ========================================================================= */
"use strict";

const BUDDY_POSES = {
  neutral: { src: "/static/buddy/neutral.png", line: "Ready when you are!" },
  yawn:    { src: "/static/buddy/yawn.png",    line: "Slowly waking up… 🥱" },
  stretch: { src: "/static/buddy/stretch.png", line: "Big stretch! Let's go 🙆" },
  coffee:  { src: "/static/buddy/coffee.png",  line: "Warm drink, soft start ☕" },
  sleepy:  { src: "/static/buddy/sleepy.png",  line: "Winding down for the night 🌙" },
  ready:   { src: "/static/buddy/ready.png",   line: "Look at us go today! 🔥" },
  eat:     { src: "/static/buddy/eat.png",     line: "Mmm, fuel. Thank you 🍚" },
  drink:   { src: "/static/buddy/drink.png",   line: "Glug glug — that's the stuff 💧" },
};

/* Level unlocks change the ring, since the character art itself is fixed. */
const BUDDY_RINGS = [
  { level: 1, key: "ring-basic",  name: "Starter glow" },
  { level: 2, key: "ring-bright", name: "Bright aura" },
  { level: 3, key: "ring-spark",  name: "Sparkle ring" },
  { level: 5, key: "ring-gold",   name: "Golden halo" },
];

let buddyActionPose = null;
let buddyActionTimer = null;

function showBuddyPose(pose, ms = 4000) {
  buddyActionPose = pose;
  clearTimeout(buddyActionTimer);
  paintBuddy();
  buddyActionTimer = setTimeout(() => { buddyActionPose = null; paintBuddy(); }, ms);
}

function ambientPose({ score = 0, mood = null, hour = new Date().getHours(), goalHit = false }) {
  if (hour >= 22 || hour < 6) return "sleepy";
  if (mood !== null && mood <= 2) return "coffee";        // gentle company on a rough day
  if (mood !== null && mood >= 5) return "ready";
  if (hour < 9) return score >= 30 ? "stretch" : (hour < 8 ? "yawn" : "coffee");
  if (goalHit || score >= 70) return "ready";
  if (score >= 35) return "stretch";
  return "neutral";
}

function ringClass(level) {
  return BUDDY_RINGS.filter((r) => (level || 1) >= r.level).slice(-1)[0].key;
}

let buddyCtx = { score: 0, mood: null, level: 1, streak: 0, goalHit: false };

function buddyHeroHTML(d) {
  const md = (d.score.today && d.score.today.mood) || {};
  buddyCtx = {
    score: d.score.score,
    mood: md.count ? Math.round((md.total || 0) / md.count) : null,
    level: d.level,
    streak: Math.max(0, ...Object.values(d.streaks || { a: 0 })),
    goalHit: !!d.step_goal_hit,
  };
  return `<div class="buddy-stage" id="buddy-stage">${buddyInnerHTML()}</div>`;
}

function buddyInnerHTML() {
  const pose = buddyActionPose || ambientPose(buddyCtx);
  const p = BUDDY_POSES[pose] || BUDDY_POSES.neutral;
  const score = buddyCtx.score;
  const C = 2 * Math.PI * 92;
  const onFire = buddyCtx.streak >= 3;
  return `
    <button class="buddy-orb ${ringClass(buddyCtx.level)} ${onFire ? "is-fired" : ""}"
            id="buddy-tap" aria-label="Say hi to your buddy">
      <svg class="buddy-ring" viewBox="0 0 200 200" aria-hidden="true">
        <defs><linearGradient id="bRing" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#FF8A5C"/><stop offset="1" stop-color="#FF5C8A"/></linearGradient></defs>
        <circle class="track" cx="100" cy="100" r="92" fill="none" stroke-width="7"/>
        <circle class="arc" cx="100" cy="100" r="92" fill="none" stroke-width="7"
          stroke-dasharray="${C}" stroke-dashoffset="${C * (1 - score / 100)}"/>
      </svg>
      ${onFire ? `<span class="buddy-fire" aria-hidden="true">🔥</span>` : ""}
      <img class="buddy-art pose-${pose}" src="${p.src}" alt="Your buddy looks ${pose}">
    </button>
    <div class="buddy-caption">
      <span class="buddy-score">${score}<span class="muted small"> / 100</span></span>
      <span class="muted small" id="buddy-line">${esc(p.line)}</span>
      ${onFire ? `<span class="chip done">🔥 ${buddyCtx.streak}-day streak!</span>` : ""}
    </div>`;
}

function paintBuddy() {
  const stage = document.getElementById("buddy-stage");
  if (!stage) return;
  stage.innerHTML = buddyInnerHTML();
  wireBuddyTap();
}

const BUDDY_TAPS = [
  "Hey! 👋", "You're doing better than you think.", "Water break? I'll wait 💧",
  "One tiny thing counts. Promise.", "I'm basically your hype squad 📣",
  "Proud of you, no conditions.", "Look at that streak energy 🔥",
];
function wireBuddyTap() {
  const btn = document.getElementById("buddy-tap");
  if (!btn) return;
  btn.onclick = () => {
    btn.classList.remove("is-bouncing");
    void btn.offsetWidth;                        // restart the CSS animation
    btn.classList.add("is-bouncing");
    const line = document.getElementById("buddy-line");
    if (line) line.textContent = BUDDY_TAPS[Math.floor(Math.random() * BUDDY_TAPS.length)];
    buddyBurst(btn, ["💚", "✨"], 8);
  };
}

/* ---------- shared particle effect ---------- */
function buddyBurst(anchor, emojis, count = 10) {
  const host = anchor.closest(".check-row, .card, .buddy-stage") || anchor;
  if (getComputedStyle(host).position === "static") host.style.position = "relative";
  for (let i = 0; i < count; i++) {
    const s = document.createElement("span");
    s.className = "hb-particle";
    s.textContent = emojis[i % emojis.length];
    s.style.left = 30 + Math.random() * 40 + "%";
    s.style.animationDelay = (i * 45) + "ms";
    s.style.setProperty("--dx", (Math.random() * 80 - 40) + "px");
    host.appendChild(s);
    setTimeout(() => s.remove(), 1400);
  }
}

/* ---------- per-habit celebrations, each with its own buddy pose ---------- */
function habitAnimation(type, rowEl, value) {
  const POSE = { water: "drink", meal: "eat", sleep: "sleepy" };
  if (POSE[type]) showBuddyPose(POSE[type]);
  else if (type === "mood") showBuddyPose(value >= 4 ? "ready" : "coffee");

  if (!rowEl) return;
  switch (type) {
    case "water": rowEl.classList.add("fx-splash"); buddyBurst(rowEl, ["💧", "🫧"], 8); break;
    case "meal":  rowEl.classList.add("fx-pop");    buddyBurst(rowEl, ["🍚", "💚", "✨"], 9); break;
    case "sleep": rowEl.classList.add("fx-night");  buddyBurst(rowEl, ["🌙", "💤", "⭐"], 7); break;
    default:      rowEl.classList.add("fx-pop");
  }
  setTimeout(() => rowEl.classList.remove("fx-splash", "fx-pop"), 1200);
  setTimeout(() => rowEl.classList.remove("fx-night"), 2600);
}

const MOOD_FACES = { 1: "😞", 2: "😕", 3: "😐", 4: "🙂", 5: "😄" };
function moodBurst(rowEl, value) {
  if (rowEl) buddyBurst(rowEl, [MOOD_FACES[Math.round(value)] || "🙂"], 12);
}

/* ---------- steps: buddy jogs the track, finish line at the goal ---------- */
function stepsTrackHTML(steps, goal) {
  const pct = Math.max(0, Math.min(100, Math.round((steps / goal) * 100)));
  const done = steps >= goal;
  return `<div class="steps-track ${done ? "is-done" : ""}">
      <div class="steps-fill" style="width:${pct}%"></div>
      <span class="steps-runner" style="left:calc(${pct}% - 12px)">${done ? "🏃" : "🚶"}</span>
      <span class="steps-flag">${done ? "🎉" : "🏁"}</span>
    </div>`;
}

/* ---------- level-up moment ---------- */
function celebrateLevelUp(level) {
  const unlock = BUDDY_RINGS.find((r) => r.level === level);
  showBuddyPose("ready", 6000);
  modal(`<div style="text-align:center">
      <div class="levelup-burst" aria-hidden="true">🎁</div>
      <h2>Level ${level}!</h2>
      ${unlock ? `<p class="muted">Unlocked: <strong>${esc(unlock.name)}</strong> for your buddy.</p>`
               : `<p class="muted">Your buddy looks prouder already.</p>`}
      <div class="levelup-buddy ${unlock ? unlock.key : "ring-basic"}">
        <img src="${BUDDY_POSES.ready.src}" alt="">
      </div>
      <button class="btn btn-primary btn-block section-gap" data-close>Nice!</button>
    </div>`);
  const host = document.querySelector(".modal-card") || document.body;
  buddyBurst(host, ["🎉", "✨", "🎊"], 14);
}
