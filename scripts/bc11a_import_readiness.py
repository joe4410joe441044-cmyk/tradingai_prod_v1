#!/usr/bin/env python3
"""Run the BC-11A offline import readiness harness on synthetic data.

The script writes only under a fresh temporary directory. It never opens the
production knowledge store, never starts the backend, never calls a network or
an LLM, and never imports real ChatGPT or Cursor data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.knowledge_hub.import_readiness import (  # noqa: E402
    DEFAULT_ALLOWED_STORE_ROOT,
    PRODUCTION_STORE_PATH,
    SearchProbe,
    build_synthetic_corpus,
    build_synthetic_stress_export,
    run_import_readiness,
)
from backend.knowledge_hub.reader import ReaderFilters, RequestContext, open_reader  # noqa: E402


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--stress-conversations", type=int, default=100)
    parser.add_argument("--stress-messages", type=int, default=8)
    parser.add_argument("--skip-stress", action="store_true")
    args = parser.parse_args()

    workdir = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="bc11a-readiness-"))
    workdir.mkdir(parents=True, exist_ok=True)
    cleanup = not bool(args.workdir)
    try:
        corpus = build_synthetic_corpus(workdir / "corpus")
        store_path = workdir / "knowledge_store.sqlite3"
        probes = (
            SearchProbe("keyword", "alphamarker"),
            SearchProbe("phrase", "cursoralphamarker"),
            SearchProbe("source_type", "TradingAI", ReaderFilters(source_type="CHATGPT_EXPORT")),
            SearchProbe("account", "TradingAI", ReaderFilters(source_account="chatgpt_account_b")),
            SearchProbe("cursor", "cursoralphamarker", ReaderFilters(source_type="CURSOR_REPORT")),
            SearchProbe("document_identity", "cursoralphamarker"),
            SearchProbe("message_identity", "betamarker", ReaderFilters(source_account="chatgpt_account_b", conversation_id="conv-shared", message_id="m1")),
            SearchProbe("empty", "zzzznotfoundmarker"),
            SearchProbe("invalid", "!!!"),
        )
        result = run_import_readiness(
            store_path,
            chatgpt_exports={
                "chatgpt_account_a": corpus.export_a,
                "chatgpt_account_b": corpus.export_b,
            },
            report_directories=(corpus.report_dir,),
            report_roots=(corpus.report_dir,),
            indexed_at="2026-11-04T00:00:00+00:00",
            search_probes=probes,
        )
        payload = {
            "mode": "synthetic",
            "production_store": str(PRODUCTION_STORE_PATH),
            "allowed_store_root": str(DEFAULT_ALLOWED_STORE_ROOT),
            "readiness": result.to_dict(),
        }
        if not args.skip_stress:
            stress_export = build_synthetic_stress_export(
                workdir / "stress_export.zip",
                conversation_count=args.stress_conversations,
                messages_per_conversation=args.stress_messages,
            )
            stress_store = workdir / "stress_store.sqlite3"
            started = time.perf_counter()
            stress = run_import_readiness(
                stress_store,
                chatgpt_exports={"chatgpt_account_a": stress_export},
                indexed_at="2026-11-04T00:00:00+00:00",
                search_probes=(SearchProbe("stress", "stressmarker"),),
            )
            elapsed = round(time.perf_counter() - started, 6)
            reader, failure = open_reader(stress_store)
            search_seconds = None
            search_total = None
            if reader is not None:
                request = RequestContext(caller_scope="OPERATOR", caller_id="bc11a-stress")
                search_started = time.perf_counter()
                page = reader.search("stressmarker", request=request)
                search_seconds = round(time.perf_counter() - search_started, 6)
                search_total = page.total_count
                reader.close()
            payload["stress"] = {
                "conversation_count": args.stress_conversations,
                "messages_per_conversation": args.stress_messages,
                "message_count": args.stress_conversations * args.stress_messages,
                "readiness_duration_seconds": stress.duration_seconds,
                "wall_seconds": elapsed,
                "store_bytes": stress.store_bytes,
                "integrity": stress.integrity,
                "search_seconds": search_seconds,
                "search_total": search_total,
                "open_error": failure,
            }
        rendered = json.dumps(payload, indent=2, sort_keys=True)
        print(rendered)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        return 0 if result.integrity == "OK" else 1
    finally:
        if cleanup:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(_main())
