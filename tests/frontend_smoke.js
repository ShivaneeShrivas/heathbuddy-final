/* Frontend smoke test — catches "X is not defined" before users do.
   ==================================================================
   Loads the real app.js / buddy.js / features.js in Node against a tiny DOM
   stub and a fake API, then renders every screen. Any ReferenceError (a
   helper that was renamed, moved, or accidentally deleted during an edit)
   fails the run instead of shipping.

   Run:  node tests/frontend_smoke.js
   ================================================================== */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const STATIC = path.join(__dirname, "..", "healthbuddy", "static");

/* ---------- minimal DOM ---------- */
function makeEl(tag = "div") {
  const el = {
    tagName: tag, children: [], dataset: {}, style: {}, classList: {
      _s: new Set(),
      add(...c) { c.forEach((x) => this._s.add(x)); },
      remove(...c) { c.forEach((x) => this._s.delete(x)); },
      toggle(c, on) { on ? this._s.add(c) : this._s.delete(c); },
      contains(c) { return this._s.has(c); },
    },
    _html: "",
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); },
    setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
    addEventListener() {}, removeEventListener() {}, focus() {}, remove() {},
    appendChild(c) { this.children.push(c); return c; },
    insertAdjacentHTML(_, html) { this._html += html; },
    insertAdjacentElement(_, el2) { this.children.push(el2); return el2; },
    querySelector() { return makeEl(); },
    querySelectorAll() { return []; },
    closest() { return makeEl(); },
    contains() { return true; },
    get firstElementChild() { return makeEl(); },
    get offsetWidth() { return 100; },
    value: "", textContent: "", disabled: false, checked: false,
  };
  return el;
}

const document = {
  documentElement: makeEl("html"),
  body: makeEl("body"),
  createElement: (t) => makeEl(t),
  getElementById: () => makeEl(),
  querySelector: () => makeEl(),
  querySelectorAll: () => [],
  addEventListener() {},
};

/* ---------- fake API: every endpoint the screens ask for ---------- */
const CARD = { id: 1, category: "hydration", category_label: "Hydration", emoji: "💧",
  color: "#4FC3F7", title: "Sip", body: "Drink up", action_label: "Done" };
const API = {
  "/me": { user: { name: "T", onboarded: true } },
  "/dashboard": { greeting_name: "T", level: 2, xp: 90, step_goal_hit: false,
    score: { score: 40, today: { water: { count: 2, total: 2 }, meal: { count: 1, total: 1 },
      sleep: { count: 0, total: 0 }, mood: { count: 1, total: 4 } } },
    streaks: { water: 3, meal: 0, sleep: 0, mood: 1 } },
  "/daily-plan": { plan: { date: "2026-08-04", completed: 1, bonus_earned: false,
    tasks: [{ ...CARD, slot: "morning", slot_emoji: "🌅", slot_label: "Morning", done: true },
            { ...CARD, id: 2, slot: "afternoon", slot_emoji: "☀️", slot_label: "Afternoon", done: false },
            { ...CARD, id: 3, slot: "night", slot_emoji: "🌙", slot_label: "Night", done: false }] } },
  "/activity/today": { activity: { steps: 4000, source: "device_sensor" }, step_goal: 8000, connected: true },
  "/wellbeing/today": { wellbeing: { screen_time_minutes: 120, source: "android_usage" }, connected: true },
  "/nudges/next": { nudge: CARD },
  "/nudges/feed": { feed: [CARD] },
  "/cards": { categories: [{ key: "hydration", emoji: "💧", label: "Hydration", color: "#4FC3F7" }], cards: [CARD] },
  "/cards/daily": { card: { ...CARD, deep_dive: "more" } },
  "/challenges": { challenges: [{ id: 1, emoji: "💧", title: "C", description: "d", members: 2,
    joined: false, progress: 0, target: 7, ends_on: "Aug 20" }] },
  "/gamification/profile": { level: 2, xp: 90, next_at: 240, progress: 0.4,
    badges: [{ code: "first_steps", emoji: "🌱", name: "First steps", desc: "d", earned: true }] },
  "/transparency": { explanation: "why", state: [{ category: "hydration", emoji: "💧",
    label: "Hydration", color: "#4FC3F7", affinity: 0.5, pref_multiplier: 1 }] },
  "/buddies": { my_code: "HB-AAA111", buddies: [{ id: 2, name: "B", streaks: { water: 1, meal: 0, sleep: 0, mood: 0 } }] },
  "/profile": { profile: { name: "T", email: "t@e.com", avatar: "🙂", age_range: "18_24",
    gender: "female", occupation: "student", activity_level: "moderate", health_goal: "general",
    health_goals: ["general"], step_goal: 8000, notif_enabled: true, buddy_code: "HB-AAA111" } },
  "/permissions": { integrations: [{ key: "activity", emoji: "🚶", label: "Activity / Steps",
    status: "connected", why: "w" }] },
  "/notifications": { notifications: [{ id: "n", emoji: "💧", title: "T", body: "B", kind: "fun" }] },
  "/games": { games: [{ game: "memory", emoji: "🃏", label: "Memory", skill: "memory", plays: 0,
    best: null, trend_pct: null }], daily_game: "memory", play_streak: 0, brain_score: 10 },
  "/wrapped": { wrapped: { range: { start: "2026-07-29", end: "2026-08-04" }, health_score: 50,
    brain_score: 20, hydration: { glasses: 10, days: 3 }, nutrition: { meals: 5 },
    sleep: { avg_hours: 7, nights: 3 }, mood: { avg: 4, checkins: 2 }, movement_note: "n",
    nudges: { acted: 3, opened: 5, top_category: null }, games: { plays: 0, best_skill: null, trends: [] },
    xp: 50, badges: [], streaks: { water: 3 }, insights: ["i"], goals: [{ emoji: "💧", text: "g" }] },
    new_badges: [], xp_earned: 0 },
  "/cycle/status": { status: { phase: "luteal", phase_meta: { emoji: "🌙", label: "Luteal", color: "#B39DFF" },
    cycle_day: 20, next_period: "2026-08-14", days_left: 10, avg_cycle_len: 28, avg_period_len: 5,
    remind: true, gcal_export: false, checkin_due: false, cycles_recorded: 2, prediction_note: "n" } },
};

const sandbox = {
  document, console,
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, scrollTo() {}, alert() {}, confirm: () => true, requestAnimationFrame: (f) => setTimeout(f, 0),
  Capacitor: undefined, setTimeout, clearTimeout, setInterval, clearInterval,
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  location: { hash: "#home" },
  navigator: { serviceWorker: { register() {} } },
  prompt: () => "5",
  Date, Math, JSON, Object, Array, String, Number, Boolean, Promise, Error, RegExp, Set, Map,
  isNaN, parseInt, parseFloat, encodeURIComponent, performance: { now: () => 0 },
  getComputedStyle: () => ({ position: "relative" }),
  MutationObserver: class { observe() {} disconnect() {} },
  fetch: async (url) => {
    const p = String(url).replace(/^.*\/api/, "").split("?")[0];
    const body = API[p] ?? { ok: true, message: "ok", xp_earned: 0, new_badges: [] };
    return { ok: true, status: 200, json: async () => body };
  },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

/* ---------- load the real files ---------- */
for (const f of ["providers.js", "buddy.js", "app.js", "features.js"]) {
  const code = fs.readFileSync(path.join(STATIC, f), "utf8");
  try {
    vm.runInContext(code, sandbox, { filename: f });
  } catch (e) {
    console.error(`✗ ${f} failed to load: ${e.message}`);
    process.exit(1);
  }
}

/* ---------- render every screen ---------- */
const SCREENS = ["welcome", "login", "register", "onboarding", "home", "nudges",
                 "explore", "challenges", "profile", "edit_profile", "play", "wrapped",
                 "pc_offer", "pc_setup"];
let failed = 0;
(async () => {
  for (const name of SCREENS) {
    /* top-level `const views` lives in the context's lexical scope, not on the
       sandbox object, so reach it by evaluating inside the context */
    const view = vm.runInContext(`views[${JSON.stringify(name)}]`, sandbox);
    if (!view) { console.error(`✗ views.${name} does not exist`); failed++; continue; }
    try {
      await view();
      console.log(`✓ ${name}`);
    } catch (e) {
      console.error(`✗ ${name}: ${e.message}`);
      failed++;
    }
  }
  // flows reached by direct call rather than routing
  try { vm.runInContext('verifyEmailFlow("a@b.com", "", true)', sandbox); console.log("✓ verifyEmailFlow"); }
  catch (e) { console.error(`✗ verifyEmailFlow: ${e.message}`); failed++; }
  try { vm.runInContext("forgotPasswordFlow()", sandbox); console.log("✓ forgotPasswordFlow"); }
  catch (e) { console.error(`✗ forgotPasswordFlow: ${e.message}`); failed++; }

  await new Promise((r) => setTimeout(r, 400));   // let async view work settle
  console.log(failed ? `\n${failed} screen(s) broken` : "\nAll screens render ✓");
  process.exit(failed ? 1 : 0);
})();
