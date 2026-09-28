/* Cliente de la API. Adjunta el Bearer token; ante 401 intenta renovar una vez.
 * El cuerpo de /api/chat solo lleva `message` y `conversation_id`: la identidad (rol,
 * dependencia, nivel) viaja únicamente en el token y la resuelve el servidor. */
import * as auth from "./auth.js";

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export const events = new EventTarget(); // "session-expired"

async function request(path, options = {}, retry = true) {
  const token = await auth.getAccessToken();
  if (!token) { events.dispatchEvent(new Event("session-expired")); throw new ApiError(401, "Sesión expirada"); }

  let res;
  try {
    res = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}), Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new ApiError(0, "No se pudo conectar con el servidor");
  }

  if (res.status === 401 && retry && (await auth.getAccessToken({ force: true }))) return request(path, options, false);
  if (res.status === 401) { events.dispatchEvent(new Event("session-expired")); throw new ApiError(401, "Sesión expirada"); }
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail).catch(() => null);
    throw new ApiError(res.status, typeof detail === "string" ? detail : "Error del servidor");
  }
  return res.json();
}

export const getMe = () => request("/api/me");
export const sendChat = (message, conversationId) =>
  request("/api/chat", { method: "POST", body: JSON.stringify({ message, conversation_id: conversationId }) });

export async function getConfig() {
  const res = await fetch("/api/config");
  if (!res.ok) throw new Error("No se pudo leer la configuración");
  return res.json();
}
