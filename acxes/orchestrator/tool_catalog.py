"""Catálogo cerrado de herramientas: solo parámetros de negocio, sin identidad ni SQL.

Lo comparten B1 y, más adelante, el Tool Gateway de S, de modo que ambos ofrezcan al
modelo exactamente las mismas herramientas (P11 y P13). Los esquemas prohíben campos
adicionales.
"""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from acxes.orchestrator.llm_client import ToolSpec

Keyword = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class BuscarDocumentos(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keywords: list[Keyword] = Field(
        min_length=3,
        max_length=8,
        description="De 3 a 8 palabras clave y sinónimos, de hasta 40 caracteres cada una",
    )


class LeerDocumento(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: UUID = Field(description="Identificador del documento, tomado de una búsqueda previa")


TOOL_MODELS: dict[str, type[BaseModel]] = {
    "buscar_documentos": BuscarDocumentos,
    "leer_documento": LeerDocumento,
}

_DESCRIPTIONS = {
    "buscar_documentos": (
        "Busca fragmentos de documentos institucionales a partir de palabras clave "
        "y sinónimos elegidos por el asistente."
    ),
    "leer_documento": "Devuelve el contenido de un documento a partir de su identificador.",
}


def tool_specs() -> tuple[ToolSpec, ...]:
    return tuple(
        ToolSpec(name=name, description=_DESCRIPTIONS[name], parameters=model.model_json_schema())
        for name, model in TOOL_MODELS.items()
    )
