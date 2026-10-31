# BB-S4 Supervisor Runtime Acceptance

Acceptance of the held evaluation cache through the default owner
publication path.

`BotManager._publish_context_snapshot` calls `held_runtime_domains`. That
read copies the holder. The acceptance test does not pass a supervisor
fragment into `runtime_domains`.

An empty holder leaves `supervisorRuntime` UNAVAILABLE. A stored holder is
published as UNKNOWN. `evaluationCompletedAt` is the producer time.
`publishedAt` stays the publication clock. No freshness policy is added, so
the domain is not CURRENT.

`snapshot_builder.py` and `runtime_snapshot_adapter.py` are unchanged.
