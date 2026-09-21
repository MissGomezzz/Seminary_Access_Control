"""'Interfaz Chat' de la arquitectura Unsecure (B1).

A propósito no valida identidad: se elige un usuario de prueba de la tabla `users`, sin
contraseña ni token, y el chat le cree. La arquitectura Secure valida un JWT en la API de
borde y congela un SecurityContext (ver `docs/ARQUITECTURA.md`).

Uso:
    python -m acxes.edge_api.cli_unsecure
"""

from acxes.orchestrator.baseline_unsecure import build_default_agent
from acxes.orchestrator.llm_client import LLMInfrastructureError


def main() -> None:
    agente, repo = build_default_agent()
    usuarios = repo.list_users()
    if not usuarios:
        raise SystemExit("No hay usuarios. Ejecute: python -m acxes.db.apply")

    print("Usuarios de prueba (sin verificación de identidad):")
    for i, u in enumerate(usuarios, start=1):
        print(f"  {i}. {u.full_name} ({u.role}, {u.dept})")
    while True:
        eleccion = input("Elija un usuario por número: ").strip()
        if eleccion.isdigit() and 1 <= int(eleccion) <= len(usuarios):
            usuario = usuarios[int(eleccion) - 1]
            break

    print(f"\nHola {usuario.full_name}. Escribe tu consulta ('salir' para terminar).\n")
    while True:
        consulta = input("> ").strip()
        if consulta.lower() in {"salir", "exit", "quit"}:
            break
        if not consulta:
            continue
        try:
            turno = agente.responder(usuario, consulta)
        except LLMInfrastructureError as exc:
            print(f"Error del servicio del modelo: {exc}\n")
            continue
        print(turno.text)
        print(
            f"[fragmentos: {len(turno.chunk_ids)} | tokens: "
            f"{turno.prompt_tokens + turno.completion_tokens} | {turno.latency_s:.1f} s]\n"
        )


if __name__ == "__main__":
    main()
