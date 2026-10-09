/* Autenticación del front.
 *
 * Modo "sso": Authorization Code + PKCE contra Keycloak (docs/ARQUITECTURA.md, sección 4).
 *   - client público `acxes-chat-web`, sin secreto; la contraseña solo se escribe en Keycloak.
 *   - el front NUNCA valida la firma del JWT: eso lo hace la API de borde en cada request.
 *     Aquí solo se decodifica el payload para mostrar el perfil en pantalla (no es una
 *     decisión de seguridad).
 * Modo "demo": token de demo emitido por /api/demo/login (solo si el backend lo permite).
 *
 * Los tokens viven solo en memoria. El verificador PKCE sí usa sessionStorage porque debe
 * sobrevivir al redireccionamiento de vuelta desde Keycloak. Un despliegue institucional
 * puede sustituir este módulo por un BFF con cookie HttpOnly.
 */

const PKCE_KEY = "acxes.pkce";

let cfg = null;
let volatileSession = null;

export function init(config) { cfg = config; }

// ---------------------------------------------------------------- utilidades
const enc = new TextEncoder();

function b64url(bytes) {
  let s = "";
  new Uint8Array(bytes).forEach((b) => (s += String.fromCharCode(b)));
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(bytes = 48) {
  return b64url(crypto.getRandomValues(new Uint8Array(bytes)));
}

async function challengeS256(verifier) {
  return b64url(await crypto.subtle.digest("SHA-256", enc.encode(verifier)));
}

export function decodeJwt(token) {
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const bin = atob(part + "=".repeat((4 - (part.length % 4)) % 4));
    return JSON.parse(new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0))));
  } catch {
    return null;
  }
}

const redirectUri = () => `${location.origin}/`;
const kc = (path) => `${cfg.keycloak.url}/realms/${cfg.keycloak.realm}/protocol/openid-connect/${path}`;

// ---------------------------------------------------------------- sesión
function save(session) { volatileSession = session; }
export function current() {
  return volatileSession;
}
export function clear() { volatileSession = null; sessionStorage.removeItem(PKCE_KEY); }

function fromTokenResponse(t, mode) {
  return {
    mode,
    access_token: t.access_token,
    refresh_token: t.refresh_token || null,
    id_token: t.id_token || null,
    expires_at: Date.now() + (t.expires_in || 300) * 1000,
  };
}

export function claims() {
  const s = current();
  return s ? decodeJwt(s.access_token) : null;
}

// ---------------------------------------------------------------- SSO (PKCE)
export async function startSso() {
  const verifier = randomString(64);
  const state = randomString(24);
  const nonce = randomString(24);
  sessionStorage.setItem(PKCE_KEY, JSON.stringify({ verifier, state, nonce }));

  const params = new URLSearchParams({
    client_id: cfg.keycloak.clientId,
    redirect_uri: redirectUri(),
    response_type: "code",
    scope: "openid",
    state,
    nonce,
    code_challenge: await challengeS256(verifier),
    code_challenge_method: "S256",
  });
  location.assign(`${kc("auth")}?${params}`);
}

/** Si la URL trae ?code=… (regreso de Keycloak), completa el intercambio. Devuelve true/false. */
export async function handleRedirect() {
  const q = new URLSearchParams(location.search);
  if (!q.has("code") && !q.has("error")) return false;

  const pkce = JSON.parse(sessionStorage.getItem(PKCE_KEY) || "null");
  history.replaceState({}, "", redirectUri()); // limpia code/state de la barra de direcciones
  sessionStorage.removeItem(PKCE_KEY);

  if (q.has("error")) throw new Error(q.get("error_description") || q.get("error"));
  if (!pkce || q.get("state") !== pkce.state) throw new Error("Estado de login inválido (state)");

  const res = await fetch(kc("token"), {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: cfg.keycloak.clientId,
      code: q.get("code"),
      redirect_uri: redirectUri(),
      code_verifier: pkce.verifier, // Keycloak lo compara con el code_challenge del paso 1
    }),
  });
  if (!res.ok) throw new Error("Keycloak rechazó el intercambio de código");
  const tokens = await res.json();

  const idc = tokens.id_token ? decodeJwt(tokens.id_token) : null;
  if (idc && idc.nonce !== pkce.nonce) throw new Error("Nonce inválido");

  save(fromTokenResponse(tokens, "sso"));
  return true;
}

async function refreshSso(session) {
  if (!session.refresh_token) return false;
  const res = await fetch(kc("token"), {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      client_id: cfg.keycloak.clientId,
      refresh_token: session.refresh_token,
    }),
  });
  if (!res.ok) return false;
  save(fromTokenResponse(await res.json(), "sso"));
  return true;
}

// ---------------------------------------------------------------- demo
export async function demoLogin(userId) {
  const res = await fetch("/api/demo/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId }),
  });
  if (!res.ok) throw new Error("No se pudo iniciar la sesión de demo");
  save(fromTokenResponse(await res.json(), "demo"));
}

// ---------------------------------------------------------------- token vigente
/** Devuelve un access token vigente (renovándolo si está por vencer) o null. */
export async function getAccessToken({ force = false } = {}) {
  const s = current();
  if (!s) return null;
  const expiring = s.expires_at - Date.now() < 20_000;
  if (!force && !expiring) return s.access_token;
  if (s.mode === "sso" && (await refreshSso(s))) return current().access_token;
  return expiring || force ? null : s.access_token;
}

export function logout() {
  const s = current();
  clear();
  if (s && s.mode === "sso" && cfg) {
    const p = new URLSearchParams({ post_logout_redirect_uri: redirectUri(), client_id: cfg.keycloak.clientId });
    if (s.id_token) p.set("id_token_hint", s.id_token);
    location.assign(`${kc("logout")}?${p}`);
    return true; // la página se recarga desde Keycloak
  }
  return false;
}
