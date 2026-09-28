import * as auth from "./auth.js";
import * as api from "./api.js";
import * as store from "./store.js";
import * as ui from "./ui.js";

const $ = (id) => document.getElementById(id);

const state = { cfg: null, profile: null, conversations: [], activeId: null, busy: false };

// ---------------------------------------------------------------- vistas
function show(view) {
  $("view-login").hidden = view !== "login";
  $("view-app").hidden = view !== "app";
}

function showLogin(message) {
  show("login");
  if (message) ui.toast(message, "error");
}

function renderDemoUsers() {
  const users = state.cfg.demo_users || [];
  $("demo-box").hidden = users.length === 0;
  $("demo-users").replaceChildren(...users.map((u) =>
    ui.h("button", { class: "demo-user", type: "button", onclick: () => loginDemo(u.id) },
      ui.h("span", { class: "avatar" }, ui.initials(u.full_name)),
      ui.h("span", {}, ui.h("b", {}, u.full_name), ui.h("small", {}, `${u.role} · ${u.dept}`)))));
}

async function loginDemo(userId) {
  try {
    await auth.demoLogin(userId);
    await enterApp();
  } catch (e) {
    ui.toast(e.message, "error");
  }
}

// ---------------------------------------------------------------- app
async function enterApp() {
  try {
    state.profile = await api.getMe();
  } catch (e) {
    if (e.status === 501) return showLogin("La API de borde real aún no está implementada (etapa 2). Usa el modo demo.");
    if (e.status !== 401) ui.toast(e.message, "error");
    return showLogin();
  }
  const p = state.profile;
  $("demo-banner").hidden = !state.cfg.demo || auth.current()?.mode !== "demo";
  ui.renderUserCard(p);
  ui.renderScope(p);

  state.conversations = store.load(p.user_id, p.policy_version);
  show("app");
  newConversation();
  $("input").focus();
}

function persist() { store.save(state.profile.user_id, state.profile.policy_version, state.conversations); }
const active = () => state.conversations.find((c) => c.id === state.activeId);

function refreshHistory() { ui.renderHistory(state.conversations, state.activeId, openConversation); }

function newConversation() {
  state.activeId = null;
  renderThread([]);
  refreshHistory();
}

function openConversation(id) {
  state.activeId = id;
  renderThread(active()?.turns || []);
  refreshHistory();
}

function renderThread(turns) {
  const thread = $("thread");
  thread.replaceChildren();
  if (!turns.length) {
    thread.append(ui.emptyState(state.profile, (q) => { $("input").value = q; submit(); }));
    return;
  }
  for (const t of turns) {
    thread.append(ui.userMessage(t.q));
    thread.append(t.result ? ui.botMessage(t.result, state.profile) : ui.errorMessage(t.error));
  }
  scrollDown();
}

function scrollDown() { const m = $("messages"); m.scrollTop = m.scrollHeight; }

async function submit() {
  const input = $("input");
  const text = input.value.trim();
  if (!text || state.busy) return;

  setBusy(true);
  input.value = ""; autosize();

  let conv = active();
  if (!conv) {
    conv = { id: store.newId(), title: text.slice(0, 48), turns: [] };
    state.conversations.unshift(conv);
    state.activeId = conv.id;
    $("thread").replaceChildren();
    refreshHistory();
  }

  $("thread").append(ui.userMessage(text), ui.typingMessage());
  scrollDown();

  const turn = { q: text };
  try {
    turn.result = await api.sendChat(text, conv.id);
  } catch (e) {
    if (e.status === 401) { setBusy(false); return; } // session-expired ya redirige
    turn.error = e.status === 429 ? "Demasiadas solicitudes. Espera un momento e inténtalo de nuevo."
      : e.status === 0 ? e.message : "No pude procesar tu consulta. Inténtalo de nuevo.";
  }
  $("typing")?.remove();
  conv.turns.push(turn);
  $("thread").append(turn.result ? ui.botMessage(turn.result, state.profile) : ui.errorMessage(turn.error));
  persist();
  scrollDown();
  setBusy(false);
  input.focus();
}

function setBusy(b) { state.busy = b; $("btn-send").disabled = b; }

function autosize() {
  const t = $("input");
  t.style.height = "auto";
  t.style.height = `${Math.min(t.scrollHeight, 144)}px`;
}

function logout() {
  if (state.profile) store.purge(state.profile.user_id);
  state.profile = null;
  if (!auth.logout()) showLogin();
}

// ---------------------------------------------------------------- arranque
async function boot() {
  try {
    state.cfg = await api.getConfig();
  } catch (e) {
    show("login");
    return ui.toast("No se pudo contactar al servidor de ACXES.", "error");
  }
  auth.init(state.cfg);
  renderDemoUsers();

  $("btn-sso").addEventListener("click", () => auth.startSso());
  $("btn-new").addEventListener("click", newConversation);
  $("btn-logout").addEventListener("click", logout);
  $("btn-scope").addEventListener("click", () => {
    const panel = $("scope");
    const open = panel.dataset.open !== "true";
    panel.dataset.open = String(open);
    $("btn-scope").setAttribute("aria-expanded", String(open));
  });
  $("composer").addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  $("input").addEventListener("input", autosize);
  $("input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
  });
  api.events.addEventListener("session-expired", () => {
    auth.clear(); state.profile = null; showLogin("Tu sesión expiró. Inicia sesión de nuevo.");
  });

  try {
    await auth.handleRedirect(); // regreso de Keycloak con ?code=
  } catch (e) {
    auth.clear();
    return showLogin(e.message);
  }

  if (auth.current()) await enterApp();
  else show("login");
}

boot();
