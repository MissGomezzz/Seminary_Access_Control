"""Regla mínima contra agregaciones que permitan identificar individuos."""

import unicodedata

MIN_AGGREGATION_GROUP = 3


class AggregationDenied(Exception):
    """El tamaño de la cohorte no permite publicar un agregado."""


def require_minimum_group(group_size: int, minimum: int = MIN_AGGREGATION_GROUP) -> None:
    if group_size < minimum:
        raise AggregationDenied(f"se requieren al menos {minimum} personas")


def aggregate_salary(values: list[int], group_size: int | None = None) -> dict[str, int]:
    """Devuelve solo un agregado para una cohorte suficientemente grande."""
    size = len(values) if group_size is None else group_size
    require_minimum_group(size)
    if len(values) != size or not values:
        raise AggregationDenied("cohorte inconsistente")
    return {"group_size": size, "total": sum(values), "average": round(sum(values) / size)}


def is_aggregate_request(query: str) -> bool:
    folded = "".join(
        char
        for char in unicodedata.normalize("NFD", query.lower())
        if unicodedata.category(char) != "Mn"
    )
    return any(
        phrase in folded
        for phrase in (
            "nomina global",
            "salario promedio",
            "salarios de todos",
            "total de salarios",
            "promedio de salarios",
            "reporte global de nomina",
        )
    )
