/* ORION Companion Web Control Center Client */

const state = {
  ws: null,
  currentView: "console",
  catalog: [],
  history: [],
  pendingConfirmation: null,
  wakeWordActive: false,
  listening: false,
  backendTtsAvailable: true,
  ttsEnabled: true,
  lastResponseText: "",
};

const VIEW_TITLES = {
  console: "Assistant Console",
  shortcuts: "Commands, Applications & Websites",
  history: "Command History & Screenshots",
  notes: "Notes & Reminders",
  settings: "Settings & Audio Diagnostics",
};

// ------------------------------------------------------------------ //
// API Helper & Toasts
// ------------------------------------------------------------------ //
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let payload = {};
  try {
    payload = await res.json();
  } catch {
    payload = {};
  }
  if (!res.ok) {
    const msg = payload.detail || `Request failed (${res.status})`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return payload;
}

function showToast(message, type = "info") {
  const stack = document.getElementById("toast-stack");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  stack.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

function formatTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso;
  }
}

// ------------------------------------------------------------------ //
// Navigation & Subtabs
// ------------------------------------------------------------------ //
function switchView(viewName) {
  state.currentView = viewName;
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === viewName);
  });
  document.querySelectorAll(".view").forEach((sec) => {
    sec.classList.toggle("active", sec.id === `view-${viewName}`);
  });
  document.getElementById("page-title").textContent = VIEW_TITLES[viewName] || "ORION";
  document.getElementById("sidebar").classList.remove("open");

  if (viewName === "shortcuts") {
    loadCatalog();
    loadApps();
    loadWebsites();
  } else if (viewName === "history") {
    loadHistory();
    loadScreenshots();
  } else if (viewName === "notes") {
    loadNotes();
  } else if (viewName === "settings") {
    loadSettingsAndDevices();
  }
}

function setupSubtabs() {
  document.querySelectorAll(".subtabs").forEach((group) => {
    const parent = group.parentElement;
    group.querySelectorAll(".subtab").forEach((tab) => {
      tab.addEventListener("click", () => {
        const target = tab.dataset.subtab;
        group.querySelectorAll(".subtab").forEach((t) => t.classList.toggle("active", t === tab));
        parent.querySelectorAll(".subview").forEach((sv) => {
          sv.classList.toggle("active", sv.id === `subview-${target}`);
        });
      });
    });
  });
}

// ------------------------------------------------------------------ //
// Live Status & WebSocket Connection
// ------------------------------------------------------------------ //
function updateStateUI(statusState, detail) {
  const chip = document.getElementById("state-chip");
  chip.textContent = String(statusState || "idle").replace(/_/g, " ").toUpperCase();
  chip.className = `state-chip state-${statusState || "idle"}`;
  if (detail) {
    document.getElementById("status-detail").textContent = detail;
  }

  const orb = document.getElementById("btn-voice-listen");
  const orbLabel = document.getElementById("orb-label");
  orb.classList.toggle("listening", statusState === "listening");
  if (statusState === "listening") {
    orbLabel.textContent = "Listening...";
  } else if (statusState === "recognizing") {
    orbLabel.textContent = "Recognizing Speech...";
  } else if (statusState === "speaking") {
    orbLabel.textContent = "Speaking Response...";
  } else if (statusState === "processing" || statusState === "executing") {
    orbLabel.textContent = "Executing...";
  } else {
    orbLabel.textContent = "Click to Speak";
  }
}

function applyStatusSnapshot(status) {
  if (!status) return;
  updateStateUI(status.state, status.detail);

  state.backendTtsAvailable = Boolean(status.tts_available);
  if (typeof status.tts_enabled === "boolean") {
    state.ttsEnabled = status.tts_enabled;
    syncVoiceMuteUI();
  }

  state.wakeWordActive = Boolean(status.wake_word_active);
  const wakeBtn = document.getElementById("btn-wake-toggle");
  wakeBtn.textContent = state.wakeWordActive ? "👂 Wake Word: ON" : "👂 Wake Word: OFF";
  wakeBtn.className = state.wakeWordActive ? "btn btn-primary btn-sm" : "btn btn-secondary btn-sm";

  const hwMeta = document.getElementById("sidebar-hw-meta");
  const micStr = status.microphone_available ? "Mic Ready" : "No Mic";
  const ttsStr = status.tts_available ? "TTS Ready" : "TTS Off";
  hwMeta.textContent = `${micStr} • ${ttsStr}`;

  if (status.stats) {
    document.getElementById("stat-total-cmds").textContent = status.stats.total_commands ?? 0;
    document.getElementById("stat-apps-count").textContent = status.stats.apps_count ?? 0;
    document.getElementById("stat-shots-count").textContent = status.stats.screenshots_count ?? 0;
    document.getElementById("nav-notes-count").textContent = status.stats.open_notes_count ?? 0;
  }

  if (Array.isArray(status.pending_confirmations) && status.pending_confirmations.length > 0) {
    openConfirmationModal(status.pending_confirmations[0]);
  }

  renderDiagnostics(status);
}

function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/events`);
  const pill = document.getElementById("ws-status");

  ws.onopen = () => {
    pill.classList.add("connected");
    pill.querySelector("span:last-child").textContent = "Live Sync Connected";
  };

  ws.onclose = () => {
    pill.classList.remove("connected");
    pill.querySelector("span:last-child").textContent = "Reconnecting...";
    setTimeout(connectWebSocket, 2500);
  };

  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "status_snapshot") {
        applyStatusSnapshot(msg.status);
      } else if (msg.type === "state_changed") {
        updateStateUI(msg.state, msg.detail);
      } else if (msg.type === "command_result" && msg.result) {
        appendFeedItem(msg.result);
        refreshStatus();
        if (state.currentView === "history") {
          loadHistory();
          loadScreenshots();
        } else if (state.currentView === "notes") {
          loadNotes();
        }
      } else if (msg.type === "confirmation_required" && msg.confirmation) {
        openConfirmationModal(msg.confirmation);
      } else if (msg.type === "confirmation_resolved") {
        closeConfirmationModal();
      } else if (msg.type === "wake_word_status") {
        refreshStatus();
      } else if (msg.type === "settings_updated" && msg.settings) {
        state.ttsEnabled = String(msg.settings.tts_enabled) !== "false";
        if (!state.ttsEnabled) stopBrowserSpeech();
        syncVoiceMuteUI();
      }
    } catch {
      // Ignore malformed frames
    }
  };
  state.ws = ws;
}

async function refreshStatus() {
  try {
    const status = await api("/api/status");
    applyStatusSnapshot(status);
  } catch (err) {
    console.error(err);
  }
}

// ------------------------------------------------------------------ //
// Speech Controls & Browser SpeechSynthesis Fallback
// ------------------------------------------------------------------ //
const spokenResultKeys = new Set();

function syncVoiceMuteUI() {
  const btn = document.getElementById("btn-tts-mute");
  const chk = document.getElementById("chk-speak-response");
  if (btn) {
    btn.textContent = state.ttsEnabled ? "🔊 Voice: ON" : "🔇 Voice: Muted";
  }
  if (chk) {
    chk.checked = state.ttsEnabled;
  }
}

function stopBrowserSpeech() {
  try {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
  } catch {
    // Gracefully ignore unavailable browser speech errors
  }
}

function speakInBrowser(text) {
  const cleaned = (text || "").trim();
  if (!cleaned || !("speechSynthesis" in window)) return false;
  try {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(cleaned);
    utterance.onerror = () => {};
    window.speechSynthesis.speak(utterance);
    return true;
  } catch {
    return false;
  }
}

async function replayResponseText(text) {
  const target = (text || state.lastResponseText || "").trim();
  if (!target) {
    showToast("No response available to replay yet.", "info");
    return;
  }
  stopBrowserSpeech();
  if (state.backendTtsAvailable) {
    try {
      const res = await api("/api/tts/replay", {
        method: "POST",
        body: JSON.stringify({ text: target }),
      });
      if (res.queued) return;
    } catch {
      // Fall through to browser speech fallback
    }
  }
  if (!speakInBrowser(target)) {
    showToast("Speech output is unavailable on this device.", "warning");
  }
}

// ------------------------------------------------------------------ //
// Feed & Command Execution
// ------------------------------------------------------------------ //
const renderedResultKeys = new Set();

function appendFeedItem(result, { fromHistory = false } = {}) {
  const dedupKey = result.history_id
    ? `hist-${result.history_id}`
    : `${result.timestamp}-${result.input_text}-${result.status}`;
  if (renderedResultKeys.has(dedupKey)) return;
  renderedResultKeys.add(dedupKey);

  const responseText = (result.response_text || "").trim();
  if (responseText) {
    state.lastResponseText = responseText;
  }

  // Fallback to browser SpeechSynthesis only when backend SAPI5 TTS is unavailable
  if (
    !fromHistory &&
    !state.backendTtsAvailable &&
    state.ttsEnabled &&
    responseText &&
    !spokenResultKeys.has(dedupKey)
  ) {
    spokenResultKeys.add(dedupKey);
    speakInBrowser(result.spoken_text || responseText);
  }

  const emptyEl = document.getElementById("feed-empty");
  if (emptyEl) emptyEl.style.display = "none";

  const feed = document.getElementById("conversation-feed");
  const item = document.createElement("div");
  item.className = "feed-item";
  item.innerHTML = `
    <div class="feed-item-user">
      <span>You: ${escapeHtml(result.input_text || "(voice)")}</span>
      <span class="muted">${formatTime(result.timestamp)}</span>
    </div>
    <div class="feed-item-response">${escapeHtml(result.response_text)}</div>
    <div class="feed-meta">
      <span class="pill pill-${escapeHtml(result.status)}">${escapeHtml(result.status)}</span>
      <span class="pill pill-intent">${escapeHtml(result.intent)}</span>
      <span>${result.execution_ms ?? 0} ms</span>
      <button type="button" class="btn btn-ghost btn-sm feed-replay-btn" title="Replay this response">🔊 Replay</button>
    </div>
  `;
  const replayBtn = item.querySelector(".feed-replay-btn");
  if (replayBtn) {
    replayBtn.addEventListener("click", () => replayResponseText(result.spoken_text || responseText));
  }
  feed.appendChild(item);
  feed.scrollTop = feed.scrollHeight;
}

async function runCommand(text, inputMode = "text") {
  const trimmed = (text || "").trim();
  if (!trimmed) {
    showToast("Please enter a command first.", "warning");
    return;
  }
  const sendBtn = document.getElementById("btn-send-command");
  const speak = document.getElementById("chk-speak-response").checked;
  sendBtn.disabled = true;
  sendBtn.textContent = "Running...";
  try {
    const res = await api("/api/commands/execute", {
      method: "POST",
      body: JSON.stringify({ text: trimmed, input_mode: inputMode, speak_response: speak }),
    });
    appendFeedItem(res);
    if (res.requires_confirmation && res.confirmation_request) {
      openConfirmationModal(res.confirmation_request);
    }
    if (state.currentView !== "console") {
      showToast(res.response_text, res.success ? "success" : "warning");
    }
    await refreshStatus();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = "Run Command";
  }
}

async function triggerVoiceListen() {
  if (state.listening) return;
  stopBrowserSpeech();
  state.listening = true;
  const orb = document.getElementById("btn-voice-listen");
  orb.classList.add("busy", "listening");
  try {
    const res = await api("/api/commands/listen", { method: "POST" });
    appendFeedItem(res);
    if (res.requires_confirmation && res.confirmation_request) {
      openConfirmationModal(res.confirmation_request);
    }
    if (!res.success) {
      showToast(res.response_text, "warning");
    }
    await refreshStatus();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    state.listening = false;
    orb.classList.remove("busy", "listening");
  }
}

// ------------------------------------------------------------------ //
// Confirmation Modal (Synopsis Section 6)
// ------------------------------------------------------------------ //
function openConfirmationModal(req) {
  state.pendingConfirmation = req;
  document.getElementById("confirm-action-desc").textContent = req.action_description;
  document.getElementById("confirm-warning-msg").textContent = req.warning_message;
  document.getElementById("confirm-modal").classList.remove("hidden");
}

function closeConfirmationModal() {
  state.pendingConfirmation = null;
  document.getElementById("confirm-modal").classList.add("hidden");
}

async function submitConfirmation(approved) {
  if (!state.pendingConfirmation) return;
  const token = state.pendingConfirmation.token;
  closeConfirmationModal();
  try {
    const res = await api("/api/commands/confirm", {
      method: "POST",
      body: JSON.stringify({ token, approved }),
    });
    appendFeedItem(res);
    showToast(res.response_text, approved ? "success" : "warning");
    await refreshStatus();
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ------------------------------------------------------------------ //
// Catalog, Applications & Websites CRUD
// ------------------------------------------------------------------ //
async function loadCatalog() {
  const data = await api("/api/commands/supported");
  state.catalog = data.commands || [];
  renderCatalog("");
}

function renderCatalog(filterText) {
  const q = (filterText || "").toLowerCase();
  const grid = document.getElementById("catalog-grid");
  const filtered = state.catalog.filter(
    (c) =>
      !q ||
      c.title.toLowerCase().includes(q) ||
      c.category.toLowerCase().includes(q) ||
      c.examples.some((e) => e.toLowerCase().includes(q))
  );
  grid.innerHTML = filtered
    .map(
      (c) => `
      <div class="catalog-item">
        <div class="catalog-cat">${escapeHtml(c.category)}</div>
        <strong>${escapeHtml(c.title)}</strong>
        <div class="catalog-examples">
          ${c.examples
            .map(
              (ex) =>
                `<button class="chip-btn catalog-run-btn" data-cmd="${escapeHtml(ex)}">▶ ${escapeHtml(ex)}</button>`
            )
            .join("")}
        </div>
      </div>
    `
    )
    .join("");

  grid.querySelectorAll(".catalog-run-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      switchView("console");
      runCommand(btn.dataset.cmd, "quick_action");
    });
  });
}

async function loadApps() {
  const data = await api("/api/apps");
  const apps = data.apps || [];
  document.getElementById("apps-table-count").textContent = `${apps.length} apps`;
  const tbody = document.getElementById("apps-tbody");
  tbody.innerHTML = apps
    .map(
      (app) => `
      <tr>
        <td><code>${escapeHtml(app.alias)}</code></td>
        <td>${escapeHtml(app.display_name)}</td>
        <td class="muted">${escapeHtml(app.executable_path)}</td>
        <td>${app.requires_confirmation ? '<span class="pill pill-pending_confirmation">Confirm</span>' : '<span class="pill pill-success">Safe</span>'}</td>
        <td class="row-actions">
          <button class="btn btn-secondary btn-sm" data-launch-app="${escapeHtml(app.alias)}">Launch</button>
          <button class="btn btn-danger btn-sm" data-del-app="${app.id}">Delete</button>
        </td>
      </tr>
    `
    )
    .join("");

  tbody.querySelectorAll("[data-launch-app]").forEach((b) => {
    b.addEventListener("click", () => runCommand(`open ${b.dataset.launchApp}`, "quick_action"));
  });
  tbody.querySelectorAll("[data-del-app]").forEach((b) => {
    b.addEventListener("click", async () => {
      await api(`/api/apps/${b.dataset.delApp}`, { method: "DELETE" });
      showToast("Application removed.", "success");
      loadApps();
      refreshStatus();
    });
  });
}

async function loadWebsites() {
  const data = await api("/api/websites");
  const sites = data.websites || [];
  document.getElementById("websites-table-count").textContent = `${sites.length} sites`;
  const tbody = document.getElementById("websites-tbody");
  tbody.innerHTML = sites
    .map(
      (s) => `
      <tr>
        <td><code>${escapeHtml(s.alias)}</code></td>
        <td>${escapeHtml(s.display_name)}</td>
        <td><a href="${escapeHtml(s.url)}" target="_blank" rel="noreferrer" style="color:var(--accent)">${escapeHtml(s.url)}</a></td>
        <td class="row-actions">
          <button class="btn btn-secondary btn-sm" data-open-site="${escapeHtml(s.alias)}">Open</button>
          <button class="btn btn-danger btn-sm" data-del-site="${s.id}">Delete</button>
        </td>
      </tr>
    `
    )
    .join("");

  tbody.querySelectorAll("[data-open-site]").forEach((b) => {
    b.addEventListener("click", () => runCommand(`open ${b.dataset.openSite}`, "quick_action"));
  });
  tbody.querySelectorAll("[data-del-site]").forEach((b) => {
    b.addEventListener("click", async () => {
      await api(`/api/websites/${b.dataset.delSite}`, { method: "DELETE" });
      showToast("Website bookmark removed.", "success");
      loadWebsites();
      refreshStatus();
    });
  });
}

// ------------------------------------------------------------------ //
// History & Screenshots
// ------------------------------------------------------------------ //
async function loadHistory() {
  const search = document.getElementById("history-search").value.trim();
  const status = document.getElementById("history-status-filter").value;
  const qs = new URLSearchParams({ limit: "150", search, status });
  const data = await api(`/api/history?${qs.toString()}`);
  state.history = data.items || [];
  const tbody = document.getElementById("history-tbody");

  if (!state.history.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="muted" style="text-align:center;padding:24px;">No matching history entries.</td></tr>`;
    return;
  }

  tbody.innerHTML = state.history
    .map(
      (h) => `
      <tr>
        <td class="muted">${formatTime(h.created_at)}</td>
        <td><code>${escapeHtml(h.input_mode)}</code></td>
        <td><strong>${escapeHtml(h.input_text)}</strong></td>
        <td><span class="pill pill-intent">${escapeHtml(h.matched_intent)}</span></td>
        <td><span class="pill pill-${escapeHtml(h.status)}">${escapeHtml(h.status)}</span></td>
        <td>${escapeHtml(h.response_text)}</td>
        <td class="row-actions">
          <button class="btn btn-secondary btn-sm" data-rerun="${escapeHtml(h.input_text)}">Re-run</button>
          <button class="btn btn-danger btn-sm" data-del-hist="${h.id}">✕</button>
        </td>
      </tr>
    `
    )
    .join("");

  tbody.querySelectorAll("[data-rerun]").forEach((b) => {
    b.addEventListener("click", () => {
      switchView("console");
      runCommand(b.dataset.rerun, "quick_action");
    });
  });
  tbody.querySelectorAll("[data-del-hist]").forEach((b) => {
    b.addEventListener("click", async () => {
      await api(`/api/history/${b.dataset.delHist}`, { method: "DELETE" });
      loadHistory();
      refreshStatus();
    });
  });
}

async function loadScreenshots() {
  const data = await api("/api/screenshots");
  const shots = data.screenshots || [];
  const grid = document.getElementById("screenshots-grid");
  if (!shots.length) {
    grid.innerHTML = `<div class="muted" style="padding:20px;">No screenshots captured yet. Click "Capture Screenshot Now" or say "Take a screenshot".</div>`;
    return;
  }
  grid.innerHTML = shots
    .map(
      (s) => `
      <div class="shot-card">
        <img src="/api/screenshots/${s.id}/file" alt="${escapeHtml(s.filename)}" loading="lazy" />
        <div class="shot-body">
          <div class="shot-name">${escapeHtml(s.filename)}</div>
          <div class="shot-meta">${s.width}×${s.height} • ${formatTime(s.captured_at)}</div>
          <div class="row-actions">
            <button class="btn btn-secondary btn-sm" data-open-shot="${s.id}">Open</button>
            <a class="btn btn-secondary btn-sm" href="/api/screenshots/${s.id}/file" download="${escapeHtml(s.filename)}">Save</a>
            <button class="btn btn-danger btn-sm" data-del-shot="${s.id}">Delete</button>
          </div>
        </div>
      </div>
    `
    )
    .join("");

  grid.querySelectorAll("[data-open-shot]").forEach((b) => {
    b.addEventListener("click", async () => {
      try {
        await api(`/api/screenshots/${b.dataset.openShot}/open`, { method: "POST" });
        showToast("Opened screenshot on desktop.", "success");
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  });
  grid.querySelectorAll("[data-del-shot]").forEach((b) => {
    b.addEventListener("click", async () => {
      await api(`/api/screenshots/${b.dataset.delShot}`, { method: "DELETE" });
      showToast("Screenshot deleted.", "success");
      loadScreenshots();
      refreshStatus();
    });
  });
}

// ------------------------------------------------------------------ //
// Notes CRUD
// ------------------------------------------------------------------ //
async function loadNotes() {
  const data = await api("/api/notes");
  const notes = data.notes || [];
  const list = document.getElementById("notes-list");
  if (!notes.length) {
    list.innerHTML = `<li class="muted" style="padding:16px;text-align:center;">No notes yet. Add one above or say "Take a note ...".</li>`;
    return;
  }
  list.innerHTML = notes
    .map(
      (n) => `
      <li class="note-item ${n.is_completed ? "done" : ""}">
        <input type="checkbox" ${n.is_completed ? "checked" : ""} data-toggle-note="${n.id}" />
        <span class="note-text">${escapeHtml(n.content)}</span>
        <span class="muted">${formatTime(n.created_at)}</span>
        <button class="btn btn-danger btn-sm" data-del-note="${n.id}">Delete</button>
      </li>
    `
    )
    .join("");

  list.querySelectorAll("[data-toggle-note]").forEach((chk) => {
    chk.addEventListener("change", async () => {
      await api(`/api/notes/${chk.dataset.toggleNote}`, {
        method: "PATCH",
        body: JSON.stringify({ is_completed: chk.checked }),
      });
      loadNotes();
      refreshStatus();
    });
  });
  list.querySelectorAll("[data-del-note]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await api(`/api/notes/${btn.dataset.delNote}`, { method: "DELETE" });
      showToast("Note deleted.", "success");
      loadNotes();
      refreshStatus();
    });
  });
}

// ------------------------------------------------------------------ //
// Settings & Diagnostics
// ------------------------------------------------------------------ //
async function loadSettingsAndDevices() {
  const [settingsRes, micsRes, voicesRes, statusRes] = await Promise.all([
    api("/api/settings"),
    api("/api/devices/microphones"),
    api("/api/devices/voices"),
    api("/api/status"),
  ]);

  const s = settingsRes.settings || {};
  document.getElementById("set-user-name").value = s.user_name || "User";
  document.getElementById("set-default-city").value = s.default_city || "Delhi";
  document.getElementById("set-stt-lang").value = s.stt_language || "en-IN";
  document.getElementById("set-stt-engine").value = s.stt_engine || "google";
  document.getElementById("set-tts-rate").value = s.tts_rate || "175";
  document.getElementById("lbl-tts-rate").textContent = s.tts_rate || "175";
  document.getElementById("set-tts-vol").value = s.tts_volume || "0.95";
  document.getElementById("lbl-tts-vol").textContent = `${Math.round(Number(s.tts_volume || 0.95) * 100)}%`;
  document.getElementById("set-tts-enabled").checked = s.tts_enabled !== "false";
  document.getElementById("set-confirm-guard").checked = s.require_confirmation !== "false";

  const micSel = document.getElementById("set-mic-index");
  micSel.innerHTML = `<option value="">System Default Microphone</option>` +
    (micsRes.microphones || [])
      .map((m) => `<option value="${m.index}">[${m.index}] ${escapeHtml(m.name)}</option>`)
      .join("");
  micSel.value = s.stt_mic_index || "";

  const voiceSel = document.getElementById("set-tts-voice");
  voiceSel.innerHTML = `<option value="">System Default Voice</option>` +
    (voicesRes.voices || [])
      .map((v) => `<option value="${escapeHtml(v.id)}">${escapeHtml(v.name)}</option>`)
      .join("");
  voiceSel.value = s.tts_voice_id || "";

  renderDiagnostics(statusRes);
}

function renderDiagnostics(status) {
  const container = document.getElementById("diagnostics-list");
  if (!container || !status) return;
  const ai = status.ai_provider || { provider: "none", configured: false, model: "none" };
  const rows = [
    ["Voice Input (PyAudio)", status.microphone_available ? "Available" : "No Microphone Detected", status.microphone_available],
    ["Text-to-Speech (pyttsx3)", status.tts_available ? "Active" : "Unavailable", status.tts_available],
    ["Wake-Word Listener", status.wake_word_active ? "Running" : "Standby", status.wake_word_active],
    ["Weather API (OpenWeatherMap)", status.weather_api_configured ? "Configured (.env)" : "Using wttr.in fallback", true],
    ["Optional AI Provider", ai.configured ? `${ai.provider} (${ai.model})` : "Rule-based mode (default)", true],
  ];
  container.innerHTML = rows
    .map(
      ([label, value, ok]) => `
      <div class="diag-row">
        <span>${escapeHtml(label)}</span>
        <span class="pill ${ok ? "pill-success" : "pill-unknown"}">${escapeHtml(value)}</span>
      </div>
    `
    )
    .join("");
}

// ------------------------------------------------------------------ //
// Wire Up Event Listeners
// ------------------------------------------------------------------ //
document.addEventListener("DOMContentLoaded", async () => {
  setupSubtabs();

  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });

  document.getElementById("mobile-menu-btn").addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("open");
  });

  // Console actions
  document.getElementById("btn-voice-listen").addEventListener("click", triggerVoiceListen);
  document.getElementById("command-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = document.getElementById("command-input");
    const cmd = input.value;
    input.value = "";
    runCommand(cmd, "text");
  });

  document.querySelectorAll("#quick-actions .chip-btn").forEach((btn) => {
    btn.addEventListener("click", () => runCommand(btn.dataset.cmd, "quick_action"));
  });

  document.getElementById("btn-clear-feed").addEventListener("click", () => {
    renderedResultKeys.clear();
    document.getElementById("conversation-feed").innerHTML = "";
  });

  document.getElementById("btn-tts-stop").addEventListener("click", async () => {
    stopBrowserSpeech();
    await api("/api/tts/stop", { method: "POST" });
    showToast("Stopped speech output.", "info");
  });

  document.getElementById("btn-tts-replay").addEventListener("click", () => {
    replayResponseText();
  });

  async function setVoiceEnabled(enabled) {
    state.ttsEnabled = Boolean(enabled);
    if (!state.ttsEnabled) {
      stopBrowserSpeech();
    }
    syncVoiceMuteUI();
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ settings: { tts_enabled: state.ttsEnabled } }),
      });
      showToast(state.ttsEnabled ? "Voice output unmuted." : "Voice output muted.", "info");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  document.getElementById("btn-tts-mute").addEventListener("click", () => {
    setVoiceEnabled(!state.ttsEnabled);
  });

  document.getElementById("chk-speak-response").addEventListener("change", (e) => {
    setVoiceEnabled(e.target.checked);
  });

  document.getElementById("btn-wake-toggle").addEventListener("click", async () => {
    try {
      const res = await api("/api/wake-word/toggle", {
        method: "POST",
        body: JSON.stringify({ enabled: !state.wakeWordActive }),
      });
      showToast(
        res.active ? "Wake-word listener started ('Orion')." : "Wake-word listener stopped.",
        "success"
      );
      refreshStatus();
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Confirmation modal buttons
  document.getElementById("btn-confirm-approve").addEventListener("click", () => submitConfirmation(true));
  document.getElementById("btn-confirm-cancel").addEventListener("click", () => submitConfirmation(false));

  // Catalog search
  document.getElementById("catalog-search").addEventListener("input", (e) => renderCatalog(e.target.value));

  // App CRUD form
  document.getElementById("app-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/apps", {
        method: "POST",
        body: JSON.stringify({
          alias: document.getElementById("app-alias").value,
          display_name: document.getElementById("app-name").value,
          executable_path: document.getElementById("app-exe").value,
          arguments: document.getElementById("app-args").value,
          requires_confirmation: document.getElementById("app-confirm").checked,
        }),
      });
      e.target.reset();
      showToast("Application saved and ready for voice/text launch!", "success");
      loadApps();
      refreshStatus();
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Website CRUD form
  document.getElementById("website-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/websites", {
        method: "POST",
        body: JSON.stringify({
          alias: document.getElementById("site-alias").value,
          display_name: document.getElementById("site-name").value,
          url: document.getElementById("site-url").value,
        }),
      });
      e.target.reset();
      showToast("Website bookmark saved!", "success");
      loadWebsites();
      refreshStatus();
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // History controls
  document.getElementById("history-search").addEventListener("input", loadHistory);
  document.getElementById("history-status-filter").addEventListener("change", loadHistory);
  document.getElementById("btn-export-history").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify(state.history, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "orion_command_history.json";
    a.click();
  });
  document.getElementById("btn-clear-history").addEventListener("click", async () => {
    if (!confirm("Permanently clear all saved command history?")) return;
    await api("/api/history", { method: "DELETE" });
    showToast("Command history cleared.", "success");
    loadHistory();
    refreshStatus();
  });

  // Screenshots controls
  document.getElementById("btn-capture-now").addEventListener("click", async () => {
    try {
      const res = await api("/api/screenshots/capture", { method: "POST" });
      showToast(res.response_text, res.success ? "success" : "error");
      loadScreenshots();
      refreshStatus();
    } catch (err) {
      showToast(err.message, "error");
    }
  });
  document.getElementById("btn-refresh-shots").addEventListener("click", loadScreenshots);

  // Notes form
  document.getElementById("note-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("note-input");
    if (!input.value.trim()) {
      showToast("Enter note text first.", "warning");
      return;
    }
    try {
      await api("/api/notes", {
        method: "POST",
        body: JSON.stringify({ content: input.value.trim() }),
      });
      input.value = "";
      showToast("Note saved.", "success");
      loadNotes();
      refreshStatus();
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Settings controls
  document.getElementById("set-tts-rate").addEventListener("input", (e) => {
    document.getElementById("lbl-tts-rate").textContent = e.target.value;
  });
  document.getElementById("set-tts-vol").addEventListener("input", (e) => {
    document.getElementById("lbl-tts-vol").textContent = `${Math.round(Number(e.target.value) * 100)}%`;
  });
  document.getElementById("btn-calibrate-mic").addEventListener("click", async () => {
    showToast("Calibrating microphone for ambient noise...", "info");
    const res = await api("/api/devices/calibrate", { method: "POST" });
    if (res.success) {
      showToast(`Microphone calibrated (threshold: ${res.energy_threshold}).`, "success");
    } else {
      showToast(res.error || "Calibration failed.", "error");
    }
  });
  document.getElementById("btn-test-tts").addEventListener("click", async () => {
    const res = await api("/api/tts/test", { method: "POST", body: JSON.stringify({}) });
    showToast(res.queued ? "Playing test speech..." : "TTS engine unavailable.", res.queued ? "success" : "warning");
  });
  document.getElementById("settings-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          settings: {
            user_name: document.getElementById("set-user-name").value.trim() || "User",
            default_city: document.getElementById("set-default-city").value.trim() || "Delhi",
            stt_mic_index: document.getElementById("set-mic-index").value,
            stt_language: document.getElementById("set-stt-lang").value,
            stt_engine: document.getElementById("set-stt-engine").value,
            tts_voice_id: document.getElementById("set-tts-voice").value,
            tts_rate: document.getElementById("set-tts-rate").value,
            tts_volume: document.getElementById("set-tts-vol").value,
            tts_enabled: document.getElementById("set-tts-enabled").checked,
            require_confirmation: document.getElementById("set-confirm-guard").checked,
          },
        }),
      });
      showToast("Settings saved and applied!", "success");
      refreshStatus();
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Initial load
  await refreshStatus();
  const initialHistory = await api("/api/history?limit=8");
  (initialHistory.items || []).reverse().forEach((h) => {
    appendFeedItem(
      {
        history_id: h.id,
        input_text: h.input_text,
        response_text: h.response_text,
        intent: h.matched_intent,
        status: h.status,
        execution_ms: h.execution_ms,
        timestamp: h.created_at,
      },
      { fromHistory: true }
    );
  });
  connectWebSocket();
});
