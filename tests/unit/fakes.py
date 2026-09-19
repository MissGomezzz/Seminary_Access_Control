"""Doble de prueba de InstitutionalRepository. Misma forma que Postgres,
cero red. Se usa en los tests de la línea base Unsecure y, más adelante,
en los del sistema Secure para comparar comportamiento con el mismo corpus."""

from acxes.db.repository import Employee, Team

SEED_EMPLOYEES = [
    Employee(id=1, full_name="Sofía Ariza", role="empleado", team_id=1, salary=4_200_000),
    Employee(id=2, full_name="Belén Quintero", role="empleado", team_id=1, salary=4_350_000),
    Employee(id=3, full_name="Ángela Gómez", role="empleado", team_id=2, salary=4_100_000),
    Employee(id=4, full_name="Laura Martínez", role="supervisor", team_id=1, salary=6_800_000),
    Employee(id=5, full_name="Carlos Rentería", role="supervisor", team_id=2, salary=7_000_000),
    Employee(id=6, full_name="Diego Fajardo", role="administrador", team_id=None, salary=9_500_000),
]

SEED_TEAMS = [
    Team(id=1, name="Nómina", manager_id=4),
    Team(id=2, name="Investigación", manager_id=5),
]


class InMemoryInstitutionalRepository:
    def __init__(
        self,
        employees: list[Employee] | None = None,
        teams: list[Team] | None = None,
    ) -> None:
        self._employees = list(employees if employees is not None else SEED_EMPLOYEES)
        self._teams = list(teams if teams is not None else SEED_TEAMS)

    def find_employee_by_name(self, full_name: str) -> Employee | None:
        needle = full_name.strip().lower()
        for e in self._employees:
            if needle in e.full_name.lower():
                return e
        return None

    def list_team_members(self, team_id: int) -> list[Employee]:
        return [e for e in self._employees if e.team_id == team_id]

    def payroll_report(self) -> list[Employee]:
        return list(self._employees)

    def team_led_by(self, manager_full_name: str) -> Team | None:
        manager = self.find_employee_by_name(manager_full_name)
        if manager is None:
            return None
        for t in self._teams:
            if t.manager_id == manager.id:
                return t
        return None
