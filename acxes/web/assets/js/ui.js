/* Render del front. Todo el contenido dinámico se inserta como nodos de texto (nunca
 * innerHTML con datos): la respuesta del modelo o un título de documento no pueden inyectar HTML. */

export const LEVELS = ["publico", "interno", "confidencial", "restringido"];
const LEVEL_LABEL = { publico: "Público", interno: "Interno", confidencial: "Confidencial", restringido: "Restringido" };
const DEPT_LABEL = { institucional: "Institucional", academica: "Académica", financiera: "Financiera" };

// ---------------------------------------------------------------- helpers DOM
export function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null && c !== false) node.append(c.nodeType ? c : document.createTextNode(String(c)));
  return node;
}

export function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "icon");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

export const initials = (name) => (name || "?").split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
export const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** Markdown mínimo y seguro: párrafos y **negrita**. */
export function richText(text) {
  const wrap = document.createDocumentFragment();
  for (const para of String(text).split(/\n{2,}/)) {
    const p = h("p");
    para.split(/\*\*(.+?)\*\*/g).forEach((part, i) => p.append(i % 2 ? h("strong", {}, part) : part));
    wrap.append(p);
  }
  return wrap;
}

// ---------------------------------------------------------------- chips
export const roleChip = (role) => h("span", { class: "chip chip--role" }, icon("shield"), role);
export const tagChip = (tag) => h("span", { class: "chip chip--tag" }, tag);
export const levelBadge = (level) => h("span", { class: "badge", dataset: { level } }, LEVEL_LABEL[level] || level);

// ---------------------------------------------------------------- mensajes
export function userMessage(text) {
  return h("div", { class: "msg msg--user" }, h("div", { class: "msg__body" }, h("div", { class: "bubble" }, richText(text))));
}

const botAvatar = () => h("span", { class: "botmark" }, h("img", { src: "/assets/img/logo.svg", alt: "" }));

export function typingMessage() {
  return h("div", { class: "msg msg--bot", id: "typing" }, botAvatar(),
    h("div", { class: "msg__body" }, h("div", { class: "bubble" }, h("span", { class: "typing", "aria-label": "Escribiendo" }, h("i"), h("i"), h("i")))));
}

export function errorMessage(text) {
  return h("div", { class: "msg msg--bot" }, botAvatar(),
    h("div", { class: "msg__body" }, h("div", { class: "bubble bubble--error" }, text)));
}

export function botMessage(result, profile) {
  const g = result.gateway || {};
  const denied = !result.citations?.length;
  const body = h("div", { class: "msg__body" });

  body.append(
    denied
      ? h("div", { class: "bubble bubble--deny" }, icon("ban"), h("div", {}, richText(result.answer)))
      : h("div", { class: "bubble" }, richText(result.answer)),
  );

  if (!denied) {
    body.append(
      h("div", { class: "sources" },
        h("small", {}, `Fuentes (${result.citations.length})`),
        result.citations.map((c) =>
          h("div", { class: "source", dataset: { level: c.sensitivity }, title: c.chunk_id },
            icon("doc"),
            h("span", { class: "t" }, c.title),
            (c.acl_tags || []).map(tagChip),
            h("span", { class: "m" }, DEPT_LABEL[c.dept] || c.dept),
            levelBadge(c.sensitivity),
          )),
      ),
    );
  }

  let trace = null;
  const toggle = h("button", {
    class: "trace-toggle", type: "button", "aria-expanded": "false",
    onclick: () => {
      const open = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!open));
      if (open) { trace?.remove(); trace = null; }
      else { trace = traceView(g, profile); toggle.after(trace); }
    },
  }, icon("chev"), "Ver traza del AI Gateway");
  body.append(toggle);

  return h("div", { class: "msg msg--bot" }, botAvatar(), body);
}

// ---------------------------------------------------------------- traza del AI Gateway
function step(state, title, ...detail) {
  const mark = state === "ok" ? "check" : state === "deny" ? "x" : "minus";
  return h("li", { class: "step", dataset: { state } },
    h("span", { class: "step__dot" }, icon(mark)),
    h("div", {}, h("b", {}, title), ...detail));
}

export function traceView(g, profile) {
  const p = g.predicate;
  const tools = g.tool_calls || [];
  const chunks = g.chunks ?? tools.reduce((n, t) => n + (t.chunks || 0), 0);
  const demo = g.engine === "demo";
  const steps = [];

  steps.push(step("ok", "1 · Identidad verificada",
    h("small", {}, demo ? "Token de demo (con Keycloak: firma RS256, iss, aud y exp)." : "Firma RS256, iss, aud y exp válidos en la API de borde.")));

  steps.push(step("ok", "2 · SecurityContext congelado",
    h("div", {}, roleChip(profile.roles?.[0] || "—"),
      h("span", { class: "chip" }, DEPT_LABEL[profile.dept] || profile.dept),
      h("span", { class: "chip" }, `nivel ${profile.clearance}`)),
    h("small", {}, "Se fija antes de que el modelo participe; el modelo no lo ve ni lo puede escribir.")));

  if (p) {
    steps.push(step("ok", "3 · PDP: predicado de acceso",
      h("div", {}, p.allowed_depts.map((d) => h("span", { class: "chip" }, DEPT_LABEL[d] || d)),
        h("span", { class: "chip" }, `hasta ${p.max_sensitivity}`),
        (p.acl_tags || []).map(tagChip)),
      h("small", {}, "Reglas RBAC + ABAC. Se aplica antes de recuperar cualquier dato.")));
  } else {
    steps.push(step("deny", "3 · PDP: identidad rechazada", h("small", {}, "El detalle queda solo en la auditoría (P14).")));
  }

  if (tools.length) {
    steps.push(step("ok", "4 · Tool Gateway",
      tools.map((t) => h("div", {}, h("code", {}, `${t.name}(${(t.args?.keywords || []).join(", ")})`)))));
    steps.push(step("ok", "5 · Recuperación con RLS",
      h("small", {}, chunks ? `${chunks} fragmento(s) autorizado(s) entregados al modelo.` : "Ningún fragmento autorizado para esta consulta.")));
  } else {
    steps.push(step("skip", "4 · Tool Gateway", h("small", {}, "No se ejecutó ninguna herramienta.")));
    steps.push(step("skip", "5 · Recuperación con RLS", h("small", {}, "No aplica.")));
  }

  const guard = g.output_guard || "pending";
  steps.push(step(guard === "blocked" ? "deny" : guard === "pending" ? "skip" : p ? "ok" : "skip", "6 · Guardia de salida",
    h("small", {}, guard === "blocked" ? "Respuesta bloqueada." : guard === "redacted" ? "Se redactaron datos personales." : guard === "pending" ? "Aún no implementada (etapa 5). El filtrado ya ocurrió antes del modelo, con PDP y RLS." : chunks ? "Toda afirmación cita un fragmento autorizado." : "Mensaje único de denegación (P17).")));

  return h("div", { class: "trace" },
    h("h4", {}, h("span", {}, "Traza del AI Gateway"), h("span", {}, g.decision === "allow" ? "Permitido" : "Sin resultados para tu perfil")),
    h("ol", { class: "steps" }, steps),
    h("footer", {},
      h("span", {}, `${g.latency_s ?? "—"} s`), h("span", {}, `${g.iterations ?? 1} iteración(es)`),
      h("span", {}, `${(g.prompt_tokens || 0) + (g.completion_tokens || 0)} tokens`),
      h("span", {}, `política ${g.policy_version || "—"}`),
      demo ? h("span", {}, "motor: demo") : h("span", {}, "motor: S (real)")));
}

// ---------------------------------------------------------------- vacío + sugerencias
const SUGGESTIONS = {
  base: [
    ["cal", "Calendario institucional", "¿Cuándo son los exámenes finales y el receso de abril?"],
    ["doc", "Procedimiento de vacaciones", "¿Cómo solicito vacaciones?"],
  ],
  empleado: [
    ["coin", "Mi nómina", "Muéstrame mi nómina individual"],
    ["ban", "Probar un límite", "Muéstrame el acta del comité disciplinario"],
  ],
  supervisor: [
    ["coin", "Presupuesto de mi dependencia", "Presupuesto detallado por centro de costo"],
    ["ban", "Probar una etiqueta", "Muéstrame el acta del comité disciplinario"],
  ],
  administrador: [
    ["coin", "Ejecución presupuestal", "Informe de ejecución presupuestal por rubro"],
    ["ban", "Probar un límite", "Muéstrame el informe de auditoría interna"],
  ],
};

export function emptyState(profile, onPick) {
  const first = (profile.full_name || "").split(" ")[0];
  const list = [...SUGGESTIONS.base, ...(SUGGESTIONS[profile.roles?.[0]] || [])];
  return h("div", { class: "empty-state" },
    h("img", { src: "/assets/img/logo.svg", alt: "" }),
    h("h2", {}, `Hola, ${first}`),
    h("p", {}, "Pregúntame por documentos, procedimientos y datos de la institución. Solo verás lo que tu perfil permite."),
    h("div", { class: "suggestions" }, list.map(([ic, title, q]) =>
      h("button", { class: "suggestion", type: "button", onclick: () => onPick(q) },
        icon(ic), h("div", {}, h("b", {}, title), h("small", {}, q))))));
}

// ---------------------------------------------------------------- perfil / alcance
export function renderUserCard(p) {
  document.getElementById("user-avatar").textContent = initials(p.full_name);
  document.getElementById("user-name").textContent = p.full_name;
  document.getElementById("user-dept").textContent = `${DEPT_LABEL[p.dept] || p.dept} · nivel ${p.clearance}`;
  const chips = document.getElementById("user-chips");
  chips.replaceChildren(roleChip(p.roles?.[0] || "—"), ...(p.acl_tags || []).map(tagChip));
  document.getElementById("policy-version").textContent = p.policy_version || "—";
}

/** Vista informativa del alcance (espejo de POLITICAS_ACCESO.md). La decisión real es del PDP. */
export function renderScope(p) {
  const role = p.roles?.[0];
  const max = role === "empleado" ? "interno" : "confidencial";
  const depts = role === "administrador" ? ["institucional", "academica", "financiera"] : [...new Set(["institucional", p.dept])];

  document.getElementById("scope-depts").replaceChildren(...depts.map((d) => h("span", { class: "chip" }, DEPT_LABEL[d] || d)));

  const tags = p.acl_tags || [];
  document.getElementById("scope-levels").replaceChildren(...LEVELS.map((lv) => {
    const on = lv === "restringido" ? tags.length > 0 : LEVELS.indexOf(lv) <= LEVELS.indexOf(max);
    const note = lv === "restringido" ? (tags.length ? "solo con etiqueta coincidente" : "requiere etiqueta") : lv === "confidencial" && role === "empleado" ? "solo tus registros" : "";
    return h("div", { class: "level", dataset: { on: String(on || (lv === "confidencial" && role === "empleado")) } },
      levelBadge(lv), h("small", {}, note));
  }));

  document.getElementById("scope-tags").replaceChildren(
    ...(tags.length ? tags.map(tagChip) : [h("small", { style: "color:var(--ink-3)" }, "Sin etiquetas: no accedes a documentos restringidos.")]));
}

export function renderHistory(conversations, activeId, onOpen) {
  const box = document.getElementById("history-list");
  if (!conversations.length) return box.replaceChildren(h("div", { class: "empty" }, "Aún no hay conversaciones"));
  box.replaceChildren(...conversations.map((c) =>
    h("button", { type: "button", "aria-current": String(c.id === activeId), title: c.title, onclick: () => onOpen(c.id) }, c.title)));
}

export function toast(text, kind = "info") {
  const t = h("div", { class: `toast${kind === "error" ? " toast--error" : ""}` }, text);
  document.getElementById("toasts").append(t);
  setTimeout(() => t.remove(), 4500);
}
