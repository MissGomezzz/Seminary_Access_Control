"""'Interfaz Chat' de la arquitectura Unsecure (Hito 1).

A propósito no valida identidad de ninguna forma: el diagrama de la sección 4
del Hito 1 no incluye un paso de login/token, y añadirlo aquí adelantaría
trabajo de la arquitectura Secure (Keycloak, ver `docs/ARQUITECTURA.md`).
El "usuario" que se pide abajo es solo una etiqueta para el historial de la
sesión, no una credencial.

Uso:
    python -m acxes.edge_api.cli_unsecure
"""

from acxes.orchestrator.baseline_unsecure import build_default_agent


def main() -> None:
    agente = build_default_agent()
    usuario = input("Nombre de usuario (sin verificar, solo para el historial): ").strip()
    print(f"\nHola {usuario}. Escribe tu consulta ('salir' para terminar).\n")

    while True:
        consulta = input("> ").strip()
        if consulta.lower() in {"salir", "exit", "quit"}:
            break
        respuesta = agente.responder(usuario, consulta)
        print(respuesta, "\n")


if __name__ == "__main__":
    main()
