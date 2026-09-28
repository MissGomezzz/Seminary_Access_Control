/* Historial de conversaciones, por usuario y versión de política (P15): si la política
 * cambia, el historial guardado se descarta. sessionStorage: se borra al cerrar la pestaña. */
const key = (sub, version) => `acxes.history.${sub}.${version}`;

export function load(sub, version) {
  try { return JSON.parse(sessionStorage.getItem(key(sub, version))) || []; } catch { return []; }
}
export function save(sub, version, conversations) {
  try { sessionStorage.setItem(key(sub, version), JSON.stringify(conversations.slice(0, 30))); } catch { /* cuota */ }
}
export function purge(sub) {
  Object.keys(sessionStorage).filter((k) => k.startsWith(`acxes.history.${sub}.`)).forEach((k) => sessionStorage.removeItem(k));
}
export const newId = () => `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
