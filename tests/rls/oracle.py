"""Oráculo de visibilidad escrito a mano a partir de documents/MATRIZ_ACCESO.md.

No comparte código con la política RLS ni con el PDP: parte del rol, no de las variables de
sesión, para que un error en la política no se copie a la prueba. Es también la base de la
prueba de equivalencia entre el PDP y RLS de la etapa 3.
"""

from dataclasses import dataclass

from acxes.ingestion.corpus_plan import DocSpec

# Matriz de acceso: nivel máximo por rol y si ve todas las dependencias
_ROLE_MAX = {"empleado": "interno", "supervisor": "confidencial", "administrador": "confidencial"}
_ALL_DEPTS = {"institucional", "academica", "financiera"}
_ORDER = ("publico", "interno", "confidencial", "restringido")


@dataclass(frozen=True)
class Person:
    name: str
    role: str
    dept: str
    tags: tuple[str, ...] = ()


PERSONAS = {
    "Sofía": Person("Sofía Ariza", "empleado", "financiera"),
    "Belén": Person("Belén Quintero", "empleado", "financiera"),
    "Ángela": Person("Ángela Gómez", "empleado", "academica"),
    "Laura": Person("Laura Martínez", "supervisor", "financiera", ("auditoria_interna",)),
    "Carlos": Person("Carlos Rentería", "supervisor", "academica", ("comite_disciplinario",)),
    "Diego": Person("Diego Fajardo", "administrador", "institucional"),
}


def visible(person: Person, doc: DocSpec) -> bool:
    level = _ORDER.index(doc.sensitivity)
    max_level = _ORDER.index(_ROLE_MAX[person.role])
    depts = _ALL_DEPTS if person.role == "administrador" else {"institucional", person.dept}

    # Ningún rol llega a restringido por su nivel
    if level <= max_level and doc.dept in depts:
        return True
    # Los registros propios, hasta confidencial y sin importar el tope del rol
    if doc.owner == person.name and doc.sensitivity != "restringido":
        return True
    # Restringido solo con una etiqueta coincidente, sin exigir dependencia
    return doc.sensitivity == "restringido" and bool(set(doc.acl_tags) & set(person.tags))


def expected_slugs(person: Person, specs: list[DocSpec]) -> set[str]:
    return {s.slug for s in specs if visible(person, s)}
