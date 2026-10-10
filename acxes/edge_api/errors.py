"""Errores de la API de borde. Ninguno lleva detalle hacia el cliente (P14): el motivo real
se registra en el servidor y la respuesta HTTP es siempre genérica."""


class InvalidIdentity(Exception):
    """El token es válido pero sus claims no sirven para construir un SecurityContext."""


class AccessDenied(Exception):
    """La identidad es válida, pero el PDP no le concede acceso al asistente."""


class BackendUnavailable(Exception):
    """Falló una pieza de la que depende la respuesta (PDP, base de datos o modelo).

    La respuesta es un 503 genérico y la política es fail-closed: no se entrega nada.
    """
