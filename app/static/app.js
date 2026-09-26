/* MealPrep SPA – Vanilla JS Dashboard (Glassmorphism Edition) */

let state = null;
let currentDate = todayStr();
let swapSlotId = null;
let swapCandidates = null;
let loading = false;
let activeTab = "plan";
let statsData = null;
let statsError = null;
let statsPeriod = 7;
let dayCoachData = null;

const STATUS_LABELS = {
  planned: "geplant",
  eaten: "gegessen",
  open: "offen",
};

const MEAL_COLORS = {
  "Fruehstueck": "var(--meal-breakfast)",
  "Mittagessen": "var(--meal-lunch)",
  "Abendessen": "var(--meal-dinner)",
  "Snack": "var(--meal-snack)",
  "Mitnahme": "var(--meal-packed)",
};

const DAYTYPE_LABELS = {
  arbeit: "Arbeit",
  schule: "Schule",
  urlaub: "Urlaub",
  feiertag: "Feiertag",
  krank: "Krank",
  frei: "Frei",
  wochenende: "WE",
};

// ---------------------------------------------------------------------------
// Inline SVG Icons (Lucide-style)
// ---------------------------------------------------------------------------

function icon(name, size) {
  const s = size || 18;
  const icons = {
    home: `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`,
    "book-open": `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>`,
    user: `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
    "shopping-cart": `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="21" r="1"/><circle cx="19" cy="21" r="1"/><path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12"/></svg>`,
    clock: `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
    flame: `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg>`,
    "refresh-cw": `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>`,
    "check-circle": `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`,
    "chevron-left": `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>`,
    "chevron-right": `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>`,
    plus: `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>`,
    search: `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>`,
    x: `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
    utensils: `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"/><path d="M7 2v20"/><path d="M21 15V2v0a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/></svg>`,
    pin: `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/></svg>`,
    "alert-triangle": `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
    "bar-chart": `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/></svg>`,
  };
  return icons[name] || "";
}

// ---------------------------------------------------------------------------
// Canvas Recipe Image Generator
// ---------------------------------------------------------------------------

function hashStr(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

function seededRandom(seed) {
  let s = seed;
  return function () {
    s = (s * 16807 + 0) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

function generateRecipeImage(canvas, recipeName, tags, ingredientCategories) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  const seed = hashStr(recipeName || "recipe");
  const rng = seededRandom(seed);

  // Determine meal type from tags for color
  tags = tags || [];
  const cats = ingredientCategories || [];
  let baseHue = 260; // default purple
  if (tags.includes("fruehstueck") || tags.includes("Fruehstueck")) baseHue = 30;
  else if (tags.includes("mittagessen") || tags.includes("Mittagessen")) baseHue = 155;
  else if (tags.includes("abendessen") || tags.includes("Abendessen")) baseHue = 265;
  else if (tags.includes("snack") || tags.includes("Snack")) baseHue = 200;

  // Background gradient
  const grad = ctx.createLinearGradient(0, 0, w, h);
  grad.addColorStop(0, `hsl(${baseHue}, 45%, 18%)`);
  grad.addColorStop(1, `hsl(${(baseHue + 40) % 360}, 50%, 12%)`);
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, w, h);

  // Draw abstract shapes based on categories
  const numShapes = Math.max(cats.length, 3) + Math.floor(rng() * 4);
  for (let i = 0; i < numShapes; i++) {
    const cat = cats[i % Math.max(cats.length, 1)] || "Sonstiges";
    const x = rng() * w;
    const y = rng() * h;
    const sz = 15 + rng() * 50;
    const alpha = 0.08 + rng() * 0.18;
    const hueShift = (baseHue + rng() * 80 - 40) % 360;

    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(rng() * Math.PI * 2);
    ctx.globalAlpha = alpha;

    if (cat === "Getreide" || cat === "Beilage") {
      ctx.strokeStyle = `hsl(${hueShift}, 50%, 65%)`;
      ctx.lineWidth = 2 + rng() * 3;
      ctx.beginPath();
      ctx.arc(0, 0, sz, 0, Math.PI * (1 + rng()));
      ctx.stroke();
    } else if (cat === "Protein") {
      ctx.fillStyle = `hsl(${hueShift}, 55%, 60%)`;
      ctx.beginPath();
      ctx.ellipse(0, 0, sz, sz * (0.6 + rng() * 0.4), 0, 0, Math.PI * 2);
      ctx.fill();
    } else if (cat === "Gemuese") {
      ctx.fillStyle = `hsl(${140 + rng() * 40}, 55%, 50%)`;
      ctx.beginPath();
      ctx.moveTo(0, -sz);
      ctx.bezierCurveTo(sz * 0.7, -sz * 0.5, sz * 0.5, sz * 0.5, 0, sz);
      ctx.bezierCurveTo(-sz * 0.5, sz * 0.5, -sz * 0.7, -sz * 0.5, 0, -sz);
      ctx.fill();
    } else if (cat === "Milchprodukt") {
      ctx.fillStyle = `hsl(${hueShift}, 25%, 75%)`;
      ctx.beginPath();
      ctx.arc(0, 0, sz * 0.7, 0, Math.PI * 2);
      ctx.fill();
    } else if (cat === "Obst") {
      ctx.fillStyle = `hsl(${(hueShift + 20) % 360}, 65%, 55%)`;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.arc(0, 0, sz, 0, Math.PI * (0.5 + rng() * 1.2));
      ctx.closePath();
      ctx.fill();
    } else if (cat === "Konserve") {
      ctx.fillStyle = `hsl(${hueShift}, 35%, 50%)`;
      ctx.fillRect(-sz / 2, -sz / 3, sz, sz * 0.66);
    } else if (cat === "Fett") {
      ctx.fillStyle = `hsl(${40 + rng() * 20}, 60%, 55%)`;
      ctx.beginPath();
      ctx.arc(0, 0, sz * 0.35, 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.fillStyle = `hsl(${hueShift}, 40%, 55%)`;
      ctx.beginPath();
      ctx.arc(0, 0, sz * 0.5, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.restore();
  }

  // Dot texture overlay
  ctx.globalAlpha = 0.04;
  for (let i = 0; i < 80; i++) {
    ctx.fillStyle = "#fff";
    ctx.beginPath();
    ctx.arc(rng() * w, rng() * h, 1 + rng() * 1.5, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;

  // Subtle vignette
  const vignette = ctx.createRadialGradient(w / 2, h / 2, w * 0.25, w / 2, h / 2, w * 0.75);
  vignette.addColorStop(0, "rgba(0,0,0,0)");
  vignette.addColorStop(1, "rgba(0,0,0,0.3)");
  ctx.fillStyle = vignette;
  ctx.fillRect(0, 0, w, h);
}

// Initialize canvases on a page (recipe list / detail)
function initRecipeCanvases() {
  document.querySelectorAll("canvas[data-recipe-name]").forEach(function (canvas) {
    const name = canvas.dataset.recipeName || "";
    const tags = (canvas.dataset.recipeTags || "").split(",").filter(Boolean);
    const cats = (canvas.dataset.recipeCategories || "").split(",").filter(Boolean);
    canvas.width = canvas.offsetWidth * (window.devicePixelRatio > 1 ? 2 : 1);
    canvas.height = canvas.offsetHeight * (window.devicePixelRatio > 1 ? 2 : 1);
    generateRecipeImage(canvas, name, tags, cats);
  });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function todayStr() {
  const d = new Date();
  return d.toISOString().slice(0, 10);
}

function formatDate(iso) {
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}

function formatWeekday(iso) {
  const d = new Date(iso + "T12:00:00");
  return ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"][d.getDay()];
}

function formatShortDate(iso) {
  const [, m, d] = iso.split("-");
  return `${d}.${m}.`;
}

function shiftDate(iso, days) {
  const d = new Date(iso + "T12:00:00");
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function pct(val, target) {
  if (!target || target <= 0) return 0;
  return Math.round((val / target) * 100);
}

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

function escHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function setLoading(on) {
  loading = on;
  const overlay = document.getElementById("loading-overlay");
  if (overlay) overlay.style.display = on ? "flex" : "none";
}

async function api(method, path, body) {
  const opts = { method, headers: { Accept: "application/json" } };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.error || `HTTP ${resp.status}`);
  }
  return resp.json();
}

function getMealDotColor(label) {
  if (!label) return "var(--fg-muted)";
  const l = label.toLowerCase();
  if (l.includes("frueh") || l.includes("breakfast")) return "var(--meal-breakfast)";
  if (l.includes("mittag") || l.includes("lunch")) return "var(--meal-lunch)";
  if (l.includes("mitnah") || l.includes("packed")) return "var(--meal-packed)";
  if (l.includes("abend") || l.includes("dinner")) return "var(--meal-dinner)";
  if (l.includes("snack")) return "var(--meal-snack)";
  return "var(--fg-muted)";
}

function getMealDataAttr(label) {
  if (!label) return "";
  const l = label.toLowerCase();
  if (l.includes("frueh") || l.includes("breakfast")) return "Fruehstueck";
  if (l.includes("mitnah") || l.includes("packed")) return "Mitnahme";
  if (l.includes("mittag") || l.includes("lunch")) return "Mittagessen";
  if (l.includes("abend") || l.includes("dinner")) return "Abendessen";
  if (l.includes("snack")) return "Snack";
  return "";
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadDashboard(date) {
  if (loading) return;
  currentDate = date;
  statsData = null; // reset stats when date changes
  statsError = null;
  dayCoachData = null;
  setLoading(true);
  try {
    state = await api("GET", `/api/dashboard/${date}`);
    render();
  } catch (e) {
    document.getElementById("app").innerHTML =
      `<div class="glass-card" style="border-color:var(--red)"><p style="color:var(--red)">Fehler: ${escHtml(e.message)}</p></div>`;
  } finally {
    setLoading(false);
  }
}

async function loadStats() {
  statsError = null;
  try {
    statsData = await api("GET", `/api/stats?period=${statsPeriod}`);
    render();
  } catch (e) {
    // Ohne Fehlerzustand blieb der Tab dauerhaft auf "Lade Statistik..." haengen:
    // statsData blieb null, render() wurde nie gerufen, der Nutzer wartete auf
    // etwas, das nie kam.
    statsData = null;
    statsError = e.message;
    render();
  }
}

async function loadDayCoach() {
  try {
    dayCoachData = await api("GET", `/api/day-coach/${currentDate}`);
    render();
  } catch (e) {
    dayCoachData = { error: e.message };
    render();
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

async function replanDay() {
  if (loading) return;
  setLoading(true);
  try {
    state = await api("POST", `/api/replan/${currentDate}`);
    render();
  } catch (e) {
    alert("Fehler beim Neu-Planen: " + e.message);
  } finally {
    setLoading(false);
  }
}

async function commitSlot(slotId) {
  if (loading) return;
  setLoading(true);
  try {
    state = await api("POST", `/api/slots/${slotId}/commit`);
    render();
    // Auto-scroll to day status to show next meal suggestion
    requestAnimationFrame(() => {
      const dsh = document.querySelector(".day-status-header");
      if (dsh) dsh.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  } catch (e) {
    alert("Fehler: " + e.message);
  } finally {
    setLoading(false);
  }
}

async function toggleSupplement(suppId) {
  if (loading) return;
  try {
    await api("POST", `/api/supplements/${suppId}/toggle?target_date=${currentDate}`);
    await loadDashboard(currentDate);
  } catch (e) {
    alert("Fehler: " + e.message);
  }
}

async function openSwapModal(slotId) {
  if (loading) return;
  swapSlotId = slotId;
  setLoading(true);
  try {
    swapCandidates = await api("GET", `/api/swap-candidates/${slotId}`);
    document.getElementById("swap-modal").style.display = "flex";
    renderSwapGrid();
  } catch (e) {
    alert("Fehler: " + e.message);
  } finally {
    setLoading(false);
  }
}

function closeSwapModal() {
  document.getElementById("swap-modal").style.display = "none";
  swapSlotId = null;
  swapCandidates = null;
}

async function doSwap(recipeId) {
  if (loading) return;
  setLoading(true);
  try {
    state = await api("POST", `/api/slots/${swapSlotId}/swap`, {
      recipe_id: recipeId,
    });
    closeSwapModal();
    render();
  } catch (e) {
    alert("Fehler: " + e.message);
  } finally {
    setLoading(false);
  }
}

// ---------------------------------------------------------------------------
// Adhoc Intake
// ---------------------------------------------------------------------------

function openAdhocModal() {
  document.getElementById("adhoc-modal").style.display = "flex";
  renderAdhocBody("manual");
}

function closeAdhocModal() {
  document.getElementById("adhoc-modal").style.display = "none";
}

function renderAdhocBody(tab) {
  const body = document.getElementById("adhoc-body");
  if (!body) return;

  const tabs = document.getElementById("adhoc-tab-btns");
  if (tabs) {
    tabs.querySelectorAll("button").forEach((b) => {
      b.classList.toggle("active", b.dataset.adhocTab === tab);
    });
  }

  if (tab === "recipe") {
    body.innerHTML = `
      <div class="adhoc-search">
        <input type="text" id="adhoc-recipe-search" placeholder="Rezept suchen..." autocomplete="off">
      </div>
      <div id="adhoc-recipe-results" class="adhoc-results"></div>`;
    const input = document.getElementById("adhoc-recipe-search");
    if (input) {
      input.focus();
      input.addEventListener("input", debounce(searchAdhocRecipes, 300));
    }
  } else {
    body.innerHTML = `
      <div class="adhoc-form">
        <label>Bezeichnung *</label>
        <input type="text" id="adhoc-label" placeholder="z.B. Doener vom Imbiss">
        <label>Kalorien (kcal)</label>
        <input type="number" id="adhoc-kcal" placeholder="0" min="0">
        <label>Protein (g)</label>
        <input type="number" id="adhoc-protein" placeholder="0" min="0">
        <label>Kohlenhydrate (g)</label>
        <input type="number" id="adhoc-carbs" placeholder="0" min="0">
        <label>Fett (g)</label>
        <input type="number" id="adhoc-fat" placeholder="0" min="0">
        <button data-action="submit-adhoc-manual" style="margin-top:0.75rem">${icon("plus", 16)} Eintragen</button>
      </div>`;
    const labelInput = document.getElementById("adhoc-label");
    if (labelInput) labelInput.focus();
  }
}

function debounce(fn, ms) {
  let timer;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), ms);
  };
}

async function searchAdhocRecipes() {
  const q = document.getElementById("adhoc-recipe-search")?.value || "";
  const results = document.getElementById("adhoc-recipe-results");
  if (!results) return;
  if (q.length < 2) {
    results.innerHTML = '<p style="color:var(--fg-muted)">Mindestens 2 Zeichen eingeben...</p>';
    return;
  }
  try {
    const data = await api("GET", `/rezepte/search?q=${encodeURIComponent(q)}`);
    const recipes = data.recipes || data || [];
    if (!recipes.length) {
      results.innerHTML = '<p style="color:var(--fg-muted)">Keine Rezepte gefunden.</p>';
      return;
    }
    results.innerHTML = recipes.slice(0, 10).map((r) => {
      const n = r.nutrition_per_portion || r.nutrition || {};
      return `
        <div class="adhoc-recipe-item" data-action="submit-adhoc-recipe" data-recipe-id="${r.id}">
          <strong>${escHtml(r.name)}</strong>
          <span class="meal-macros">${Math.round(n.kcal || 0)} kcal &middot; ${Math.round(n.protein_g || 0)}g P</span>
        </div>`;
    }).join("");
  } catch {
    results.innerHTML = '<p style="color:var(--fg-muted)">Suche fehlgeschlagen.</p>';
  }
}

async function submitAdhocRecipe(recipeId) {
  if (loading) return;
  setLoading(true);
  try {
    state = await api("POST", `/api/intake/log?target_date=${currentDate}`, {
      recipe_id: recipeId,
    });
    closeAdhocModal();
    render();
  } catch (e) {
    alert("Fehler: " + e.message);
  } finally {
    setLoading(false);
  }
}

async function submitAdhocManual() {
  if (loading) return;
  const label = document.getElementById("adhoc-label")?.value?.trim();
  if (!label) { alert("Bezeichnung erforderlich"); return; }
  const kcal = parseFloat(document.getElementById("adhoc-kcal")?.value) || 0;
  const protein = parseFloat(document.getElementById("adhoc-protein")?.value) || 0;
  const carbs = parseFloat(document.getElementById("adhoc-carbs")?.value) || 0;
  const fat = parseFloat(document.getElementById("adhoc-fat")?.value) || 0;

  setLoading(true);
  try {
    state = await api("POST", `/api/intake/log?target_date=${currentDate}`, {
      label: label,
      nutrition: { kcal, protein_g: protein, carbs_g: carbs, fat_g: fat },
    });
    closeAdhocModal();
    render();
  } catch (e) {
    alert("Fehler: " + e.message);
  } finally {
    setLoading(false);
  }
}

async function deleteAdhocIntake(intakeId) {
  if (loading) return;
  setLoading(true);
  try {
    state = await api("DELETE", `/api/intake/${intakeId}`);
    render();
  } catch (e) {
    alert("Fehler: " + e.message);
  } finally {
    setLoading(false);
  }
}

function renderSwapGrid() {
  if (!swapCandidates) return;
  const grid = document.getElementById("swap-grid");
  const feasibleOnly = document.getElementById("filter-feasible").checked;

  let recipes = swapCandidates.recipes;
  if (feasibleOnly) {
    recipes = recipes.filter((r) => r.feasible);
  }

  if (!recipes.length) {
    const hint = feasibleOnly
      ? "<p>Keine machbaren Rezepte. Deaktiviere den Filter, um alle zu sehen.</p>"
      : "<p>Keine Rezepte gefunden.</p>";
    grid.innerHTML = hint;
    return;
  }

  grid.innerHTML = recipes
    .map((r) => {
      const n = r.nutrition || {};
      const scoreBar = Math.round((r.score?.total || 0) * 100);
      const borderClass = r.feasible
        ? "swap-card-feasible"
        : "swap-card-infeasible";
      const missingText = r.missing_ingredients?.length
        ? `<div class="swap-missing">${r.missing_ingredients.length} fehlend</div>`
        : "";

      return `
      <div class="swap-card ${borderClass}" data-swap-recipe-id="${r.id}">
        <div class="swap-card-name">${escHtml(r.name)}</div>
        <div class="swap-card-macros">
          ${icon("flame", 12)} ${Math.round(n.kcal || 0)} kcal &middot;
          ${Math.round(n.protein_g || 0)}g P &middot;
          ${Math.round(n.carbs_g || 0)}g K &middot;
          ${Math.round(n.fat_g || 0)}g F
        </div>
        <div class="swap-card-meta">
          <span>${icon("clock", 12)} ${r.cook_time_min} min</span>
          <span class="swap-score-badge">Score: ${scoreBar}%</span>
        </div>
        <div class="swap-score-bar-bg"><div class="swap-score-bar-fill" style="width:${scoreBar}%"></div></div>
        ${missingText}
        ${r.tags?.length ? `<div class="swap-card-tags">${r.tags.map((t) => `<span class="badge">${escHtml(t)}</span>`).join("")}</div>` : ""}
      </div>`;
    })
    .join("");
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function render() {
  if (!state) return;
  const app = document.getElementById("app");
  let body = "";
  if (activeTab === "plan") body = renderPlanTab();
  else if (activeTab === "stats") body = renderStatsTab();
  else body = renderCoachTab();

  app.innerHTML = `
    ${renderDateNav()}
    ${renderWeekView()}
    ${renderTabs()}
    ${body}
  `;
}

function renderTabs() {
  return `
    <div class="tab-bar">
      <button class="tab-btn ${activeTab === "plan" ? "active" : ""}" data-action="tab" data-tab="plan">${icon("utensils", 16)} Tagesplan</button>
      <button class="tab-btn ${activeTab === "coach" ? "active" : ""}" data-action="tab" data-tab="coach">${icon("clock", 16)} Coach</button>
      <button class="tab-btn ${activeTab === "stats" ? "active" : ""}" data-action="tab" data-tab="stats">${icon("bar-chart", 16)} Statistik</button>
    </div>`;
}

function renderCoachTab() {
  if (!dayCoachData) {
    setTimeout(loadDayCoach, 0);
    return `<section class="glass-card"><p style="color:var(--fg-muted)">Tagescoach wird geladen...</p></section>`;
  }
  if (dayCoachData.error) {
    return `<section class="glass-card" style="border-color:var(--red)"><p style="color:var(--red)">Tagescoach: ${escHtml(dayCoachData.error)}</p></section>`;
  }

  const c = dayCoachData;
  const remaining = c.remaining || {};
  const fitness = c.fitness || {};
  const plannedDay = fitness.planned_day || null;
  const workouts = fitness.workouts || [];
  const expiring = c.expiring || [];
  const dayStatus = c.day_status || {};

  const actionList = (c.actions || []).map((a) => `<li>${escHtml(a)}</li>`).join("");
  const timingList = (c.timing || []).map((t) => `
    <div class="coach-line">
      <span>${escHtml(t.label)}</span>
      <strong>${escHtml(t.text)}</strong>
    </div>`).join("");
  const expiringList = expiring.slice(0, 5).map((item) => {
    const name = item.product_name || item.name || "Vorrat";
    const amount = item.amount ?? item.quantity ?? "";
    const unit = item.unit || "";
    const expires = item.expires_at || item.expiry_date || item.best_before || "";
    return `<div class="coach-line"><span>${escHtml(name)}</span><strong>${escHtml(`${amount} ${unit}`.trim())}${expires ? ` · ${escHtml(expires)}` : ""}</strong></div>`;
  }).join("");

  return `
    <section class="coach-hero">
      <div>
        <div class="coach-kicker">${formatDate(c.date)} · ${escHtml(DAYTYPE_LABELS[c.day_type] || c.day_type || "Tag")}</div>
        <h2>${escHtml(dayStatus.status_label || "Tagesplan")}</h2>
        <p>${escHtml(dayStatus.message || "Makros, Training und Vorrat sind zusammengefuehrt.")}</p>
      </div>
      <div class="coach-score">
        <span>${Math.round((c.planned_coverage || 0) * 100)}%</span>
        <small>Planabdeckung</small>
      </div>
    </section>

    <section class="coach-grid">
      <div class="glass-card coach-card">
        <h3>Restbudget</h3>
        <div class="coach-metrics">
          <div><strong>${Math.round(remaining.kcal || 0)}</strong><span>kcal</span></div>
          <div><strong>${Math.round(remaining.protein_g || 0)}g</strong><span>Protein</span></div>
          <div><strong>${Math.round(remaining.carbs_g || 0)}g</strong><span>Kohlenhydrate</span></div>
          <div><strong>${Math.round(remaining.fat_g || 0)}g</strong><span>Fett</span></div>
        </div>
      </div>

      <div class="glass-card coach-card">
        <h3>Training</h3>
        ${fitness.reachable ? `
          <p>${plannedDay ? escHtml(plannedDay.name) : "Kein Training im aktiven Plan fuer diesen Tag."}</p>
          <p style="color:var(--fg-muted)">${workouts.length ? `${workouts.length} Workout-Eintrag${workouts.length === 1 ? "" : "e"} heute` : "Noch kein Workout erfasst."}</p>
        ` : `<p style="color:var(--fg-muted)">Fitness ist nicht erreichbar.</p>`}
      </div>

      <div class="glass-card coach-card">
        <h3>Naechste Schritte</h3>
        <ul class="coach-actions">${actionList}</ul>
      </div>

      <div class="glass-card coach-card">
        <h3>Timing</h3>
        ${timingList || `<p style="color:var(--fg-muted)">Kein besonderes Timing noetig.</p>`}
      </div>

      <div class="glass-card coach-card coach-wide">
        <h3>Ablaufende Vorraete</h3>
        ${expiringList || `<p style="color:var(--fg-muted)">Keine kritischen Vorräte in den naechsten 3 Tagen.</p>`}
      </div>
    </section>`;
}

function renderPlanTab() {
  return `
    ${renderDayStatus()}
    ${renderProgress()}
    ${renderSlots()}
    ${renderAdhocIntakes()}
    ${renderSupplements()}
    ${renderNutrientDeficits()}
    ${renderStockIndicator()}
  `;
}

function renderDayStatus() {
  const ds = state.day_status;
  if (!ds) return "";

  const statusColors = {
    on_track: "var(--status-supports)",
    attention: "var(--status-attention)",
    at_risk: "var(--status-problem)",
  };
  const statusColor = statusColors[ds.status] || "var(--fg-muted)";

  let nextMealHtml = "";
  if (ds.next_meal) {
    const nm = ds.next_meal;
    const gc = nm.goal_contribution || {};
    const badges = [];
    if (gc.protein_label) badges.push(`<span class="goal-badge goal-badge-protein">${escHtml(gc.protein_label)}</span>`);
    if (gc.carb_status && gc.carb_status !== "ok") badges.push(`<span class="goal-badge goal-badge-carb">${escHtml("K:" + gc.carb_status)}</span>`);
    if (gc.fat_status && gc.fat_status !== "ok") badges.push(`<span class="goal-badge goal-badge-fat">${escHtml("F:" + gc.fat_status)}</span>`);

    nextMealHtml = `
      <div class="next-meal-card">
        <div class="next-meal-header">
          <span class="next-meal-label">${escHtml(nm.slot_label)}</span>
          <span class="next-meal-badges">${badges.join("")}</span>
        </div>
        <div class="next-meal-name">${escHtml(nm.recipe_name)}</div>
        <div class="next-meal-reason">${escHtml(nm.reason)}</div>
        <div class="next-meal-actions">
          <button class="btn-confirm-meal" data-action="commit" data-slot-id="${nm.slot_id}">${icon("check-circle", 16)} Bestaetigen</button>
          <button class="btn-swap-icon" data-action="swap" data-slot-id="${nm.slot_id}" title="Tauschen">${icon("refresh-cw", 16)}</button>
        </div>
      </div>`;
  }

  return `
    <section class="day-status-header" style="--status-color:${statusColor}">
      <div class="day-status-top">
        <span class="day-status-badge" style="background:${statusColor}"></span>
        <span class="day-status-label">${escHtml(ds.status_label)}</span>
      </div>
      <div class="day-status-remaining">
        <div class="day-status-number">
          <span class="day-status-value">${Math.round(ds.remaining_kcal)}</span>
          <span class="day-status-unit">kcal</span>
        </div>
        <div class="day-status-number">
          <span class="day-status-value">${Math.round(ds.remaining_protein_g)}</span>
          <span class="day-status-unit">g Protein</span>
        </div>
      </div>
      <div class="day-status-message">${escHtml(ds.message)}</div>
      ${nextMealHtml}
    </section>`;
}

function renderNutrientDeficits() {
  const deficits = state.nutrient_deficits || [];
  if (!deficits.length) return "";

  const items = deficits.map((d) => {
    const pct = Math.round(d.deficit_pct * 100);
    const solutions = [];
    if (d.food_solution) solutions.push(d.food_solution);
    if (d.supplement_solution) solutions.push(d.supplement_solution);
    return `
      <div class="deficit-item">
        <div class="deficit-header">
          <span class="deficit-label">${escHtml(d.nutrient_label)}</span>
          <span class="deficit-pct">${pct}% unter Ziel</span>
        </div>
        ${solutions.length ? `<div class="deficit-solution">${escHtml(solutions.join(" oder "))}</div>` : ""}
      </div>`;
  }).join("");

  return `
    <section class="deficit-section">
      <h2>${icon("alert-triangle", 18)} Naehrstoff-Defizite</h2>
      <div class="deficit-card">${items}</div>
    </section>`;
}

function renderDateNav() {
  const isToday = currentDate === todayStr();
  return `
    <div class="date-nav">
      <button class="date-nav-btn" data-nav-shift="-1">${icon("chevron-left", 18)}</button>
      <span class="date-nav-label">${formatDate(currentDate)}</span>
      <button class="date-nav-btn" data-nav-shift="1">${icon("chevron-right", 18)}</button>
      ${!isToday ? `<button class="date-nav-today" data-nav-today="1">Heute</button>` : ""}
    </div>`;
}

function renderWeekView() {
  const days = state.days || [];
  if (!days.length) return "";

  const today = todayStr();

  const dayCells = days
    .map((day) => {
      const isoDate = day.date;
      const isToday = isoDate === today;
      const isSelected = isoDate === currentDate;
      const hasWarning = day.slots.some(
        (s) => s.feasibility_status === "infeasible"
      );

      let cls = "week-day";
      if (isToday) cls += " week-day-today";
      if (isSelected) cls += " week-day-selected";
      if (hasWarning) cls += " week-day-warning";

      const dayTypeLabel = DAYTYPE_LABELS[day.day_type] || day.day_type;
      const dayTypeClass = `week-daytype week-daytype-${day.day_type}`;

      const dots = day.slots
        .map((s) => {
          const color = getMealDotColor(s.slot_label);
          const eaten = s.status === "eaten" ? " week-dot-eaten" : "";
          return `<span class="week-dot${eaten}" style="background:${color}"></span>`;
        })
        .join("");

      return `
        <div class="${cls}" data-nav-date="${isoDate}">
          <div class="week-day-name">${formatWeekday(isoDate)}</div>
          <div class="week-day-date">${formatShortDate(isoDate)}</div>
          <div class="${dayTypeClass}">${escHtml(dayTypeLabel)}</div>
          <div class="week-dots">${dots}</div>
        </div>`;
    })
    .join("");

  return `
    <section class="week-section">
      <div class="week-grid">${dayCells}</div>
    </section>`;
}

function renderProgress() {
  const t = state.targets;
  const eaten = state.intake_totals;
  const planned = state.planned_totals;

  const macros = [
    { label: "Kalorien", key: "kcal", unit: "kcal" },
    { label: "Protein", key: "protein_g", unit: "g" },
    { label: "Kohlenhydrate", key: "carbs_g", unit: "g" },
    { label: "Fett", key: "fat_g", unit: "g" },
  ];

  function makeBar(m) {
    const target = t[m.key] || 0;
    const eat = eaten[m.key] || 0;
    const plan = planned[m.key] || 0;
    const eatPct = pct(eat, target);
    const planPct = pct(eat + plan, target);
    const totalPct = pct(eat + plan, target);
    // Semantic fill class based on total coverage
    let fillClass;
    if (eatPct > 110) fillClass = "over";
    else if (eatPct >= 90) fillClass = "done";
    else if (totalPct >= 85) fillClass = "supports";
    else if (totalPct >= 70) fillClass = "attention";
    else fillClass = "problem";

    return `
    <div class="progress-row">
      <div class="progress-label">${m.label}</div>
      <div class="progress-bar-wrap">
        <div class="progress-bar-bg">
          <div class="progress-bar-planned" style="width:${clamp(planPct, 0, 100)}%"></div>
          <div class="progress-bar-fill ${fillClass}" style="width:${clamp(eatPct, 0, 100)}%"></div>
        </div>
      </div>
      <div class="progress-numbers">${Math.round(eat)}${target ? ` / ${Math.round(target)}` : ""} ${m.unit}</div>
    </div>`;
  }

  const macroRows = macros.map(makeBar).join("");

  // Micro nutrients
  const micros = [
    { label: "Eisen", key: "iron_mg", unit: "mg", target: 10 },
    { label: "Zink", key: "zinc_mg", unit: "mg", target: 10 },
    { label: "Magnesium", key: "magnesium_mg", unit: "mg", target: 400 },
    { label: "Vitamin C", key: "vitamin_c_mg", unit: "mg", target: 100 },
    { label: "Vitamin D", key: "vitamin_d_iu", unit: "IU", target: 1000 },
    { label: "Omega-3", key: "omega3_g", unit: "g", target: 2 },
    { label: "Calcium", key: "calcium_mg", unit: "mg", target: 1000 },
  ];

  const supps = state.supplements || [];
  const hasSupplementNutrition = supps.some(s => s.nutrition != null);
  const hasMicros = hasSupplementNutrition || micros.some((m) => (eaten[m.key] || 0) > 0 || (planned[m.key] || 0) > 0);

  let microHtml = "";
  if (hasMicros) {
    const microRows = micros.map((m) => {
      const eat = eaten[m.key] || 0;
      const plan = planned[m.key] || 0;
      const ref = m.target;
      const eatPct = pct(eat, ref);
      const planPct = pct(eat + plan, ref);
      const fillClass = eatPct > 110 ? "over" : eatPct >= 90 ? "done" : "";
      return `
      <div class="progress-row">
        <div class="progress-label">${m.label}</div>
        <div class="progress-bar-wrap">
          <div class="progress-bar-bg">
            <div class="progress-bar-planned" style="width:${clamp(planPct, 0, 100)}%"></div>
            <div class="progress-bar-fill ${fillClass}" style="width:${clamp(eatPct, 0, 100)}%"></div>
          </div>
        </div>
        <div class="progress-numbers">${eat.toFixed(1)} / ${ref} ${m.unit}</div>
      </div>`;
    }).join("");

    microHtml = `
      <details class="micro-details">
        <summary>Mikros</summary>
        ${microRows}
      </details>`;
  }

  return `
    <section>
      <details open class="progress-details">
        <summary><h2 style="display:inline">${icon("flame", 18)} Tagesfortschritt</h2></summary>
        <div class="progress-section">
          ${macroRows}
          <p class="progress-legend">
            <span class="legend-eaten"></span> Gegessen
            <span class="legend-planned"></span> Geplant
          </p>
          ${microHtml}
        </div>
      </details>
    </section>`;
}

function renderSlots() {
  const slots = state.slots || [];

  let cards = "";
  if (slots.length) {
    cards = slots
      .map((s) => {
        const eatenClass = s.status === "eaten" ? "eaten" : "";
        const statusClass = `status-${s.status}`;
        const statusLabel = STATUS_LABELS[s.status] || s.status;
        const dotColor = getMealDotColor(s.slot_label);
        const mealAttr = getMealDataAttr(s.slot_label);

        // Feasibility + slot status classes
        let feasClass = "";
        if (s.feasibility_status === "infeasible") feasClass = "meal-infeasible";
        else if (s.feasibility_status === "partial") feasClass = "meal-partial";

        const slotStatusClass = s.slot_status ? `slot-${s.slot_status}` : "";

        // Pin badge
        const pinBadge = s.pinned
          ? `<span class="pin-badge" title="Manuell gewaehlt">${icon("pin", 12)}</span>`
          : "";

        // Slot status badge
        const slotStatusBadges = {
          optimal: '<span class="slot-badge slot-badge-optimal">optimal</span>',
          replace_recommended: '<span class="slot-badge slot-badge-replace">Tausch empfohlen</span>',
        };
        const slotBadge = s.status !== "eaten" && s.slot_status ? (slotStatusBadges[s.slot_status] || "") : "";

        let recipeHtml = "<em style=\"color:var(--fg-muted)\">Kein Rezept geplant</em>";
        if (s.recipe) {
          const n = s.recipe.nutrition || {};
          const instrHtml = s.recipe.instructions
            ? `<details class="meal-instructions"><summary>Zubereitung</summary><p>${escHtml(s.recipe.instructions)}</p></details>`
            : "";

          // Goal contribution badges
          const gc = s.goal_contribution || {};
          let goalBadges = "";
          if (s.status !== "eaten" && gc) {
            const badges = [];
            if (gc.protein_label) badges.push(`<span class="goal-badge goal-badge-protein">${escHtml(gc.protein_label)}</span>`);
            if (gc.carb_status === "ok") badges.push('<span class="goal-badge goal-badge-carb-ok">K:ok</span>');
            else if (gc.carb_status === "hoch") badges.push('<span class="goal-badge goal-badge-carb-high">K:hoch</span>');
            else if (gc.carb_status === "niedrig") badges.push('<span class="goal-badge goal-badge-carb-low">K:niedrig</span>');
            if (gc.fat_status === "am Limit") badges.push('<span class="goal-badge goal-badge-fat-limit">F:am Limit</span>');
            else if (gc.fat_status === "ok") badges.push('<span class="goal-badge goal-badge-fat-ok">F:ok</span>');
            goalBadges = `<div class="goal-badges">${badges.join("")}</div>`;
          }

          recipeHtml = `
          <strong>${escHtml(s.recipe.name)}</strong>
          ${goalBadges}
          <span class="meal-macros">
            ${icon("flame", 13)} ${Math.round(n.kcal || 0)} kcal &middot;
            ${Math.round(n.protein_g || 0)}g P &middot;
            ${Math.round(n.carbs_g || 0)}g K &middot;
            ${Math.round(n.fat_g || 0)}g F
          </span>
          ${instrHtml}`;
        }

        // Missing ingredients warning
        let warningHtml = "";
        if (s.missing_ingredients && s.missing_ingredients.length > 0) {
          const items = s.missing_ingredients
            .map(
              (m) =>
                `${escHtml(m.name)}: ${m.available}/${m.needed} ${escHtml(m.unit)}`
            )
            .join(", ");
          warningHtml = `
            <div class="missing-ingredients">
              ${icon("alert-triangle", 14)} <span>${s.missing_ingredients.length} Zutat(en) fehlen</span>
              <div class="missing-details">${items}</div>
            </div>`;
        }

        let actions = "";
        if (s.status !== "eaten") {
          if (s.slot_status === "replace_recommended") {
            actions = `
            <div class="meal-actions">
              <button class="btn-swap-primary" data-action="swap" data-slot-id="${s.id}">${icon("refresh-cw", 14)} Alternative waehlen</button>
            </div>`;
          } else {
            actions = `
            <div class="meal-actions">
              ${s.recipe ? `<button class="btn-confirm-meal" data-action="commit" data-slot-id="${s.id}">${icon("check-circle", 14)} Gegessen</button>` : ""}
              <button class="btn-swap-icon" data-action="swap" data-slot-id="${s.id}" title="Tauschen">${icon("refresh-cw", 14)}</button>
            </div>`;
          }
        }

        return `
        <div class="meal-card ${eatenClass} ${feasClass} ${slotStatusClass}" data-meal="${mealAttr}">
          <div class="meal-header">
            <span class="meal-type"><span class="meal-dot" style="background:${dotColor}"></span> ${escHtml(s.slot_label)} ${pinBadge} ${slotBadge}</span>
            <span class="meal-status ${statusClass}">${statusLabel}</span>
          </div>
          <div class="meal-recipe">${recipeHtml}</div>
          ${warningHtml}
          ${actions}
        </div>`;
      })
      .join("");
  } else {
    cards = '<p style="color:var(--fg-muted)">Keine Mahlzeiten fuer diesen Tag.</p>';
  }

  return `
    <section>
      <h2>${icon("utensils", 18)} Mahlzeiten</h2>
      <div class="meal-slots">${cards}</div>
      <div style="display:flex;gap:0.5rem;margin-top:0.75rem;flex-wrap:wrap">
        <button data-action="replan" class="btn-secondary">${icon("refresh-cw", 16)} Neu planen</button>
        <button data-action="open-adhoc" class="btn-secondary">${icon("plus", 16)} Mahlzeit eintragen</button>
      </div>
    </section>`;
}

function renderAdhocIntakes() {
  const intakes = state.adhoc_intakes || [];
  if (!intakes.length) return "";

  const cards = intakes.map((item) => {
    const n = item.nutrition || {};
    return `
      <div class="meal-card adhoc-card">
        <div class="meal-header">
          <span class="meal-type"><span class="meal-dot" style="background:var(--yellow)"></span> Ausserplanmaessig</span>
        </div>
        <div class="meal-recipe">
          <strong>${escHtml(item.label || "Unbenannt")}</strong>
          <span class="meal-macros">
            ${Math.round(n.kcal || 0)} kcal &middot; ${Math.round(n.protein_g || 0)}g P
          </span>
        </div>
        <div class="meal-actions">
          <button class="btn-danger" data-action="delete-intake" data-intake-id="${item.id}">${icon("x", 14)} Entfernen</button>
        </div>
      </div>`;
  }).join("");

  return `<div class="meal-slots" style="margin-top:0.5rem">${cards}</div>`;
}

function renderSupplements() {
  const supps = state.supplements || [];
  if (!supps.length) return "";

  const morgens = supps.filter((s) => s.timing === "morgens");
  const abends = supps.filter((s) => s.timing === "abends");

  function renderGroup(label, items) {
    if (!items.length) return "";
    const pills = items
      .map((s) => {
        const takenClass = s.taken_today ? "supplement-pill taken" : "supplement-pill";
        const condClass = s.category === "conditional" && s.hint ? " supplement-pill-conditional" : "";
        const hintHtml = s.hint ? `<span class="supplement-hint">${escHtml(s.hint)}</span>` : "";
        return `
          <label class="${takenClass}${condClass}" data-supplement-id="${s.id}">
            <input type="checkbox" ${s.taken_today ? "checked" : ""} data-action="toggle-supplement" data-supplement-id="${s.id}" style="display:none">
            <span class="supplement-pill-name">${escHtml(s.name)}</span>
            <span class="supplement-pill-dose">${escHtml(s.dose)}</span>
            ${hintHtml}
          </label>`;
      })
      .join("");
    return `
      <div class="supplement-group">
        <div class="supplement-timing">${escHtml(label)}</div>
        <div class="supplement-stack">${pills}</div>
      </div>`;
  }

  // Supplement hints summary
  const hints = state.supplement_hints || [];
  let hintsHtml = "";
  if (hints.length) {
    hintsHtml = `
      <div class="supplement-hints-banner">
        ${icon("alert-triangle", 14)} ${hints.map((h) => escHtml(h)).join(" &middot; ")}
      </div>`;
  }

  return `
    <section class="supplement-section">
      <h2>${icon("plus", 18)} Supplements</h2>
      ${hintsHtml}
      <div class="supplement-card">
        ${renderGroup("Morgens", morgens)}
        ${renderGroup("Abends", abends)}
      </div>
    </section>`;
}

function renderStockIndicator() {
  // ★ "Unbekannt" ist nicht "leer". Bis zum 13.09.2026 zeigte diese Kachel bei
  // jedem Ausfall von lager einen roten Balken mit "~0.0 Tage", also eine
  // Aussage ueber den Vorrat, wo gar keine Messung vorlag. Der Balken bleibt
  // in dem Fall weg, statt eine Zahl zu behaupten.
  if (!state.days_of_food_belastbar) {
    const grund = state.days_of_food_grund || "Keine Angabe verfuegbar.";
    return `
    <section class="stock-indicator">
      <h2>${icon("shopping-cart", 18)} Vorrat</h2>
      <div class="stock-bar-wrap">
        <div class="stock-label stock-label-unbekannt">Reichweite unbekannt</div>
        <div class="stock-grund">${escHtml(grund)}</div>
      </div>
    </section>`;
  }

  const days = state.days_of_food || 0;
  const maxDays = 10;
  const fillPct = clamp(Math.round((days / maxDays) * 100), 0, 100);
  let barColor = "var(--green)";
  if (days < 3) barColor = "var(--red)";
  else if (days < 5) barColor = "var(--yellow)";

  return `
    <section class="stock-indicator">
      <h2>${icon("shopping-cart", 18)} Vorrat</h2>
      <div class="stock-bar-wrap">
        <div class="stock-label">~${days.toFixed(1)} Tage</div>
        <div class="stock-bar-bg">
          <div class="stock-bar-fill" style="width:${fillPct}%;background:${barColor}"></div>
        </div>
      </div>
    </section>`;
}

// ---------------------------------------------------------------------------
// Stats Tab
// ---------------------------------------------------------------------------

function renderStatsTab() {
  if (statsError) {
    return `
      <section class="glass-card" style="border-color:var(--red)">
        <p style="color:var(--red)">Statistik konnte nicht geladen werden: ${escHtml(statsError)}</p>
        <button class="btn-secondary" data-action="stats-retry" style="margin-top:0.75rem">Erneut versuchen</button>
      </section>`;
  }
  if (!statsData) {
    loadStats();
    return '<section><p style="color:var(--fg-muted)">Lade Statistik...</p></section>';
  }

  const maxKcal = Math.max(...statsData.days.map((d) => d.kcal), 1);

  const bars = statsData.days.map((d) => {
    const hPct = Math.round((d.kcal / maxKcal) * 100);
    const dateLabel = formatShortDate(d.date);
    const weekday = formatWeekday(d.date);
    return `
      <div class="stats-bar-col" title="${weekday} ${dateLabel}: ${Math.round(d.kcal)} kcal, ${Math.round(d.protein_g)}g P">
        <div class="stats-bar" style="height:${hPct}%"></div>
        <div class="stats-bar-label">${weekday}</div>
      </div>`;
  }).join("");

  return `
    <section>
      <div class="stats-period-toggle">
        <button class="${statsPeriod === 7 ? "active" : ""}" data-action="stats-period" data-period="7">7 Tage</button>
        <button class="${statsPeriod === 30 ? "active" : ""}" data-action="stats-period" data-period="30">30 Tage</button>
      </div>
      <div class="stats-summary">
        <div class="stats-summary-item">
          <span class="stats-summary-value">${Math.round(statsData.avg_kcal)}</span>
          <span class="stats-summary-label">kcal/Tag</span>
        </div>
        <div class="stats-summary-item">
          <span class="stats-summary-value">${Math.round(statsData.avg_protein_g)}g</span>
          <span class="stats-summary-label">Protein/Tag</span>
        </div>
      </div>
      <div class="stats-chart">${bars}</div>
    </section>`;
}

// ---------------------------------------------------------------------------
// Event delegation
// ---------------------------------------------------------------------------

document.addEventListener("change", (e) => {
  const suppToggle = e.target.closest("[data-action='toggle-supplement']");
  if (suppToggle) {
    e.preventDefault();
    toggleSupplement(Number(suppToggle.dataset.supplementId));
  }
});

document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-action]");
  if (btn) {
    const action = btn.dataset.action;
    const slotId = btn.dataset.slotId;
    if (action === "replan") replanDay();
    else if (action === "swap") openSwapModal(Number(slotId));
    else if (action === "commit") commitSlot(Number(slotId));
    else if (action === "toggle-supplement") return; // handled by change event
    else if (action === "tab") {
      activeTab = btn.dataset.tab;
      statsData = null;
      statsError = null;
      if (activeTab === "coach") dayCoachData = null;
      render();
    }
    else if (action === "open-adhoc") openAdhocModal();
    else if (action === "adhoc-tab") renderAdhocBody(btn.dataset.adhocTab);
    else if (action === "submit-adhoc-manual") submitAdhocManual();
    else if (action === "submit-adhoc-recipe") submitAdhocRecipe(Number(btn.dataset.recipeId));
    else if (action === "delete-intake") deleteAdhocIntake(Number(btn.dataset.intakeId));
    else if (action === "stats-period") {
      statsPeriod = Number(btn.dataset.period);
      statsData = null;
      statsError = null;
      render();
    }
    else if (action === "stats-retry") {
      statsData = null;
      statsError = null;
      render();
    }
    return;
  }

  const navDate = e.target.closest("[data-nav-date]");
  if (navDate) {
    loadDashboard(navDate.dataset.navDate);
    return;
  }

  const navShift = e.target.closest("[data-nav-shift]");
  if (navShift) {
    loadDashboard(shiftDate(currentDate, Number(navShift.dataset.navShift)));
    return;
  }

  const navToday = e.target.closest("[data-nav-today]");
  if (navToday) {
    loadDashboard(todayStr());
    return;
  }

  const swapCard = e.target.closest("[data-swap-recipe-id]");
  if (swapCard) {
    doSwap(Number(swapCard.dataset.swapRecipeId));
    return;
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const swapModal = document.getElementById("swap-modal");
    if (swapModal && swapModal.style.display !== "none") {
      closeSwapModal();
      return;
    }
    const adhocModal = document.getElementById("adhoc-modal");
    if (adhocModal && adhocModal.style.display !== "none") {
      closeAdhocModal();
      return;
    }
  }
});

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  // SPA dashboard init
  if (document.getElementById("app")) {
    loadDashboard(todayStr());
  }
  // Recipe canvases on other pages
  initRecipeCanvases();
});
