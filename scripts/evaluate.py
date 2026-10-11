"""Punto de entrada para la evaluación comparativa.

La integración con un entorno concreto se realiza mediante los runners del proyecto; este
comando deja disponible el catálogo y valida el protocolo sin inventar resultados de una base
que no esté levantada.
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from acxes.config import get_settings
from acxes.db.repository import UserProfile
from acxes.evaluation.metrics import has_role_coverage, latency_overhead
from acxes.evaluation.runner import default_cases, run_cases
from acxes.orchestrator.baseline_unsecure import build_default_agent
from acxes.secure_app import build_secure_stack
from acxes.security_context import SecurityContext


def main() -> int:
    parser = argparse.ArgumentParser(description="Compara B1 y S con el mismo conjunto de casos.")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, default=Path("evaluation-results.json"))
    args = parser.parse_args()
    cases = default_cases()
    if not has_role_coverage(cases):
        print("Error: faltan roles en el conjunto de evaluación.", file=sys.stderr)
        return 2
    try:
        settings = get_settings()
        baseline, repository = build_default_agent()
        secure = build_secure_stack(settings)
        profiles = {profile.role: profile for profile in repository.list_users()}
        contexts = {
            role: _context(profile, secure.pdp.policy_version)
            for role, profile in profiles.items()
        }

        def run_baseline(case):
            result = baseline.responder(profiles[case.role], case.query)
            return result, result.chunk_ids

        def run_secure(case):
            result = secure.agent.respond(contexts[case.role], case.query)
            decision = secure.pdp.evaluate(contexts[case.role], "search", "documentos")
            metas = secure.retrieval.describe_chunks(
                contexts[case.role], decision, result.chunk_ids
            ) if decision.allowed else []
            return result, [meta.doc_id for meta in metas]

        baseline_metrics = run_cases(cases, run_baseline, repeats=args.repeats)
        secure_metrics = run_cases(cases, run_secure, repeats=args.repeats)
        overhead = latency_overhead(
            baseline_metrics.mean_latency_s, secure_metrics.mean_latency_s
        )
        payload = {
            "baseline": asdict(baseline_metrics),
            "secure": asdict(secure_metrics),
            "latency_overhead": overhead,
            "role_coverage": sorted({case.role for case in cases}),
        }
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return int(
            secure_metrics.leakage_rate > 0
            or secure_metrics.false_denial_rate > 0
            or overhead > 0.20
            or not has_role_coverage(cases)
        )
    except (OSError, ValueError, psycopg.Error) as exc:
        print(f"No se pudo ejecutar la evaluación: {exc}", file=sys.stderr)
        print("Verifica PostgreSQL, las variables de .env y que el esquema esté aplicado.", file=sys.stderr)
        return 2


def _context(profile: UserProfile, policy_version: str | None) -> SecurityContext:
    return SecurityContext(
        user_id=UUID(profile.user_id),
        roles=(profile.role, "default-roles-acxes"),
        dept=profile.dept,
        clearance=profile.clearance,
        acl_tags=profile.acl_tags,
        session_id=f"evaluation-{profile.user_id}",
        policy_version=policy_version,
    )


if __name__ == "__main__":
    raise SystemExit(main())
