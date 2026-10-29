"""Punto de entrada para la evaluación comparativa.

La integración con un entorno concreto se realiza mediante los runners del proyecto; este
comando deja disponible el catálogo y valida el protocolo sin inventar resultados de una base
que no esté levantada.
"""

import argparse
import json
import os
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
    parser.add_argument(
        "--retrieval-mode",
        choices=("lexical", "hybrid"),
        help="Modo de recuperación para B1 y S. Por defecto, el de .env (RETRIEVAL_MODE)",
    )
    args = parser.parse_args()
    if args.retrieval_mode:
        # B1 y S leen la configuración del entorno, así que ambos usan el mismo modo
        os.environ["RETRIEVAL_MODE"] = args.retrieval_mode
    cases = default_cases()
    if not has_role_coverage(cases):
        print("Error: faltan roles en el conjunto de evaluación.", file=sys.stderr)
        return 2
    try:
        settings = get_settings()
        baseline, repository = build_default_agent()
        secure = build_secure_stack(settings)
        profiles = {profile.full_name: profile for profile in repository.list_users()}
        contexts = {
            name: _context(profile, secure.pdp.policy_version)
            for name, profile in profiles.items()
        }

        def run_baseline(case):
            result = baseline.responder(profiles[case.user], case.query)
            doc_ids = []
            for chunk_id in result.chunk_ids:
                doc = repository.get_document(UUID(chunk_id))
                if doc is not None:
                    doc_ids.append(doc.doc_id)
            return result, doc_ids

        def run_secure(case):
            result = secure.agent.respond(contexts[case.user], case.query)
            decision = secure.pdp.evaluate(contexts[case.user], "search", "documentos")
            metas = secure.retrieval.describe_chunks(
                contexts[case.user], decision, result.chunk_ids
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
            "retrieval_mode": settings.retrieval_mode,
        }
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return int(
            secure_metrics.leakage_rate > 0
            or secure_metrics.false_denial_rate > 0
            or overhead > 0.20
            or not has_role_coverage(cases)
        )
    except (OSError, ValueError, AttributeError, KeyError, psycopg.Error) as exc:
        print(f"No se pudo ejecutar la evaluación: {exc}", file=sys.stderr)
        print("Verifica PostgreSQL, las variables de .env y que el esquema esté aplicado.", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"Error inesperado en la evaluación ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 2


def _context(profile: UserProfile, policy_version: str | None) -> SecurityContext:
    return SecurityContext(
        user_id=UUID(profile.id),
        roles=(profile.role, "default-roles-acxes"),
        dept=profile.dept,
        clearance=profile.clearance,
        acl_tags=profile.acl_tags,
        session_id=f"evaluation-{profile.id}",
        policy_version=policy_version,
    )


if __name__ == "__main__":
    raise SystemExit(main())
