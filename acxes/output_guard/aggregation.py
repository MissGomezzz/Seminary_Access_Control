"""Reglas deterministas para evitar agregados que revelen cohortes pequeñas."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

MIN_AGGREGATION_GROUP = 3


class AggregationDenied(Exception):
    """El agregado no cumple el tamaño mínimo de cohorte."""


def require_minimum_group(
    group_size: int, minimum: int = MIN_AGGREGATION_GROUP
) -> None:
    if group_size < minimum:
        raise AggregationDenied("la cohorte no permite un agregado")


def aggregate_salary(
    values: Sequence[Decimal | int | float],
    group_size: int | None = None,
    minimum: int = MIN_AGGREGATION_GROUP,
) -> dict[str, int | Decimal]:
    """Calcula total y promedio después de validar el tamaño de la cohorte."""
    if not values:
        raise AggregationDenied("la cohorte no permite un agregado")
    actual_size = len(values)
    if group_size is not None and actual_size != group_size:
        raise AggregationDenied("el tamaño de la cohorte no coincide")
    require_minimum_group(actual_size, minimum)
    total = sum((Decimal(str(value)) for value in values), Decimal(0))
    return {
        "group_size": actual_size,
        "total": total,
        "average": total / actual_size,
    }
