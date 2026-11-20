#!/usr/bin/env python3
"""Run the BC-11B approval-gated real export acceptance workflow.

Without explicit ``--account-a-export`` or ``--account-b-export`` arguments no
export is read, no store is created, and the result is
``REAL_IMPORT_EXECUTED=NO`` / ``REAL_EXPORT_ACCEPTANCE=NOT_RUN``.

A real write additionally requires ``--apply`` and an approval manifest whose
account alias, export content hash, and isolated database path match the
observed export. The script never starts the backend, never contacts a network
or an LLM, and never opens the production knowledge store.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.knowledge_hub.import_readiness import DEFAULT_ALLOWED_STORE_ROOT, SearchProbe  # noqa: E402
from backend.knowledge_hub.real_import import (  # noqa: E402
    RealImportError,
    empty_result,
    load_approval_manifest,
    run_real_import,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-a-export", default="")
    parser.add_argument("--account-b-export", default="")
    parser.add_argument("--approval-manifest", default="")
    parser.add_argument("--store", default="")
    parser.add_argument("--workdir", default="")
    parser.add_argument("--observed-at", default="")
    parser.add_argument("--indexed-at", default="")
    parser.add_argument("--allowed-store-root", default=str(DEFAULT_ALLOWED_STORE_ROOT))
    parser.add_argument("--search-probe", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", default="")
    return parser


def _write(payload: dict, output: str) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if output:
        Path(output).write_text(rendered + "\n", encoding="utf-8")


def _main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    exports: dict[str, str] = {}
    if args.account_a_export:
        exports["chatgpt_account_a"] = args.account_a_export
    if args.account_b_export:
        exports["chatgpt_account_b"] = args.account_b_export

    if not exports:
        result = empty_result()
        _write(
            {
                "mode": result.mode,
                "real_import_executed": result.real_import_executed,
                "real_export_acceptance": result.real_export_acceptance,
                "REAL_IMPORT_EXECUTED": "NO",
                "REAL_EXPORT_ACCEPTANCE": "NOT_RUN",
                "errors": list(result.errors),
                "readiness": result.to_dict(),
            },
            args.output,
        )
        return 0

    workdir = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="bc11b-real-import-"))
    workdir.mkdir(parents=True, exist_ok=True)
    store = Path(args.store) if args.store else workdir / "knowledge_store.sqlite3"
    observed_at = args.observed_at or _now()
    indexed_at = args.indexed_at or observed_at
    manifest = None
    if args.approval_manifest:
        try:
            manifest = load_approval_manifest(args.approval_manifest)
        except RealImportError as exc:
            payload = {
                "mode": "REAL",
                "real_import_executed": False,
                "real_export_acceptance": "BLOCKED",
                "REAL_IMPORT_EXECUTED": "NO",
                "REAL_EXPORT_ACCEPTANCE": "BLOCKED",
                "errors": [exc.code],
            }
            _write(payload, args.output)
            return 2
    probes = tuple(
        SearchProbe(f"cli_{index}", text) for index, text in enumerate(args.search_probe, start=1)
    )
    try:
        result = run_real_import(
            store,
            chatgpt_exports=exports,
            approval_manifest=manifest,
            observed_at=observed_at,
            indexed_at=indexed_at,
            apply=bool(args.apply),
            search_probes=probes,
            allowed_store_root=args.allowed_store_root,
        )
    except RealImportError as exc:
        payload = {
            "mode": "REAL",
            "real_import_executed": False,
            "real_export_acceptance": "BLOCKED",
            "REAL_IMPORT_EXECUTED": "NO",
            "REAL_EXPORT_ACCEPTANCE": "BLOCKED",
            "errors": [exc.code],
        }
        _write(payload, args.output)
        return 2
    _write(result.to_dict(), args.output)
    return 0 if result.real_export_acceptance in {"PASS", "PREVIEW_ONLY"} else 2


if __name__ == "__main__":
    raise SystemExit(_main())
