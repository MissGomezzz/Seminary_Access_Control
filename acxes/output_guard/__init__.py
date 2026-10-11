"""Controles deterministas aplicados antes de devolver una respuesta al cliente."""

from acxes.output_guard.guard import GuardedText, guard_text

__all__ = ["GuardedText", "guard_text"]