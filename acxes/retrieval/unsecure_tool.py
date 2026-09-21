"""'Herramienta de recuperación' de la arquitectura Unsecure (B1).

Expone las mismas dos herramientas que S (`buscar_documentos` y `leer_documento`) con
los mismos esquemas cerrados, pero sin recibir ni evaluar la identidad del usuario que
originó la consulta. Esa comprobación no existe aquí a propósito: es la brecha que el
PDP y RLS cierran en S.
"""

from pydantic import ValidationError

from acxes.config import Settings
from acxes.db.repository import InstitutionalRepository
from acxes.orchestrator.tool_catalog import TOOL_MODELS, BuscarDocumentos, LeerDocumento


class UnsecureRetrievalTool:
    def __init__(self, repo: InstitutionalRepository, settings: Settings) -> None:
        self._repo = repo
        self._k = settings.retrieval_k

    def execute(self, name: str, arguments: dict) -> dict:
        """Valida los argumentos contra el esquema cerrado y ejecuta la herramienta.
        Los errores vuelven al modelo como resultado de herramienta."""
        model = TOOL_MODELS.get(name)
        if model is None:
            return {"error": f"herramienta desconocida: {name}"}
        try:
            parsed = model.model_validate(arguments)
        except ValidationError as exc:
            return {"error": "argumentos inválidos", "detalle": _short_errors(exc)}
        if isinstance(parsed, BuscarDocumentos):
            return self.buscar_documentos(parsed)
        assert isinstance(parsed, LeerDocumento)
        return self.leer_documento(parsed)

    def buscar_documentos(self, args: BuscarDocumentos) -> dict:
        hits = self._repo.search_chunks(args.keywords, self._k)
        return {
            "resultados": [
                {"chunk_id": h.chunk_id, "doc_id": h.doc_id, "title": h.title, "content": h.content}
                for h in hits
            ]
        }

    def leer_documento(self, args: LeerDocumento) -> dict:
        doc = self._repo.get_document(args.doc_id)
        if doc is None:
            return {"encontrado": False}
        return {
            "encontrado": True,
            "doc_id": doc.doc_id,
            "title": doc.title,
            "chunks": [{"chunk_id": c.chunk_id, "content": c.content} for c in doc.chunks],
        }


def _short_errors(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
