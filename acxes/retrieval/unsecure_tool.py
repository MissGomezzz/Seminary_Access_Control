"""'Herramienta de recuperación' de la arquitectura Unsecure (secc. 4 del Hito 1).

Corresponde exactamente a la caja "pide datos" -> "despacha datos" del
diagrama: recibe una intención de negocio y devuelve datos crudos de la base,
sin recibir ni evaluar la identidad del usuario que originó la consulta.
Esa comprobación de permisos no existe en esta versión, a propósito: es la
brecha que el Hito 1 busca documentar y que el PDP (etapa futura) cierra.
"""

from dataclasses import asdict

from acxes.db.repository import InstitutionalRepository


class UnsecureRetrievalTool:
    def __init__(self, repo: InstitutionalRepository) -> None:
        self._repo = repo

    def consultar_salario(self, nombre_empleado: str) -> dict:
        empleado = self._repo.find_employee_by_name(nombre_empleado)
        if empleado is None:
            return {"encontrado": False}
        return {"encontrado": True, **asdict(empleado)}

    def consultar_equipo(self, nombre_supervisor: str) -> dict:
        equipo = self._repo.team_led_by(nombre_supervisor)
        if equipo is None:
            return {"encontrado": False}
        miembros = self._repo.list_team_members(equipo.id)
        return {
            "encontrado": True,
            "equipo": equipo.name,
            "miembros": [asdict(m) for m in miembros],
        }

    def reporte_nomina_global(self) -> dict:
        empleados = self._repo.payroll_report()
        return {"empleados": [asdict(e) for e in empleados]}
