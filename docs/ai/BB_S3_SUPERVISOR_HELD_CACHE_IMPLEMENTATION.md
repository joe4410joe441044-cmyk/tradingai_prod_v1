# BB-S3 Supervisor Held Evaluation Cache

Implemented in this worktree. The holder stores a completed MM slot and a
completed Master slot after `evaluate_mm_shadow` or `evaluate_master_shadow`
returns `COMPLETED` with `failureCode=None`.

`evaluationCompletedAt` is taken from the conversation clock at that write.
`capturedAt`, `publishedAt`, `readAt`, `assessedAt`, and `decidedAt` are not
copied. A missing or naive clock is stored as null and stays `UNKNOWN`.

`held_runtime_domains` copies the holder. It does not call
`RuntimeSnapshotAdapter.build`, `get_status`, or `get_result`. An empty holder
leaves supervisor runtime `UNAVAILABLE`. A stored holder is published as
`UNKNOWN`. No freshness TTL is added, and the domain is not `CURRENT`.

`supervisorState` is omitted. Shadow is `result.mode`. A recommendation is
not order authority. `snapshot_builder.py` and `runtime_snapshot_adapter.py`
are unchanged.
