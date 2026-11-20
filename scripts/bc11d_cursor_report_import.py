#!/usr/bin/env python3
"""Run the BC-11D approval-gated Cursor saved report import workflow.

Without ``--manifest`` no report is named, no report is read, and the result is
``REAL_REPORT_IMPORT_EXECUTED=NO`` / ``REAL_REPORT_ACCEPTANCE=NOT_RUN``.

A report is read only when ``--approval`` binds the manifest path, every report
path, the isolated store path, and the retention and log redaction policies.
A write additionally requires ``--apply``. The script never starts the backend,
never contacts a network or an LLM, and never opens the production knowledge
store for writing.
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

from backend.knowledge_hub.cursor_report_import import (  # noqa: E402
    DATA_ORIGIN_REAL,
    DATA_ORIGIN_SYNTHETIC,
    CursorImportError,
    empty_result,
    run_cursor_report_import,
)
from backend.knowledge_hub.import_readiness import DEFAULT_ALLOWED_STORE_ROOT, SearchProbe  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="")
    parser.add_argument("--approval", default="")
    parser.add_argument("--store", default="")
    parser.add_argument("--workdir", default="")
    parser.add_argument("--indexed-at", default="")
    parser.add_argument("--data-origin", choices=[DATA_ORIGIN_SYNTHETIC, DATA_ORIGIN_REAL], default=DATA_ORIGIN_SYNTHETIC)
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
    if not args.manifest:
        result = empty_result()
        _write(result.to_dict(), args.output)
        return 0

    workdir = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="bc11d-cursor-import-"))
    workdir.mkdir(parents=True, exist_ok=True)
    store = Path(args.store) if args.store else workdir / "knowledge_store.sqlite3"
    indexed_at = args.indexed_at or _now()
    probes = tuple(
        SearchProbe(f"cli_{index}", text) for index, text in enumerate(args.search_probe, start=1)
    )
    try:
        result = run_cursor_report_import(
            store,
            manifest=args.manifest,
            approval=args.approval or None,
            indexed_at=indexed_at,
            apply=bool(args.apply),
            data_origin=args.data_origin,
            search_probes=probes,
            allowed_store_root=args.allowed_store_root,
        )
    except CursorImportError as exc:
        _write(
            {
                "status": "IMPORT_FAILED",
                "REAL_REPORT_IMPORT_EXECUTED": "NO",
                "REAL_REPORT_ACCEPTANCE": "NOT_RUN" if args.data_origin != DATA_ORIGIN_REAL else "BLOCKED",
                "errors": [exc.code],
            },
            args.output,
        )
        return 2
    _write(result.to_dict(), args.output)
    return 0 if result.status != "IMPORT_FAILED" else 2


if __name__ == "__main__":
    raise SystemExit(_main())
