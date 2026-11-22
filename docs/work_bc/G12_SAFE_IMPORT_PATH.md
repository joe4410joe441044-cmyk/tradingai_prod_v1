# Work BC — G12 Safe Production Import Path

TASK_ID: `TRADINGAI-WORK-BC-G12-SAFE-IMPORT-PATH-1`

STATUS: offline implementation complete; Production import not performed.

## Purpose

`backend/knowledge_hub/production_ingest.py` is a separate, narrowly scoped
maintenance path for a future operator-authorized G12 import. It does not widen
or replace the existing isolated importer.

The existing guard in `import_readiness.assert_temporary_store` is unchanged:
the Production Store, the Production runtime root, symlinked stores, and paths
outside the temporary root continue to be rejected.

## Two states, deliberately separate

| State | Meaning |
| --- | --- |
| `PRODUCTION_ENVIRONMENT` | The canonical Production Store only. Requires operator authorization, a backup, and an audit path. |
| `ISOLATED_TEST` | A temporary Store used for offline acceptance. Cannot target Production. |

An authorization bound to `ISOLATED_TEST` is rejected by the Production guard.
A Production authorization is rejected by an isolated guard. A manifest is
data, not authorization.

## Required authorization fields

`tradingai-g12-production-authorization/v1`:

- `task_id`
- `workstream` (`BC`)
- `environment` (`PRODUCTION` or `ISOLATED_TEST`)
- `target_store` (resolved path)
- `target_store_state` (`PRESENT` or `ABSENT`)
- `target_store_sha256` (required when `PRESENT`)
- `manifest_sha256` (SHA256 of the exact candidate manifest bytes)
- `approved_record_ids`
- `approved_content_hashes`
- `approved_store_record_ids` (optional extra binding)
- `approved_operation` (`G12_PRODUCTION_IMPORT`)
- `approval_id`
- `approval_time`
- `expires_at`
- `authorized: true`
- `approval_signature_method` (`HMAC-SHA256`, required for `PRODUCTION`)
- `approval_signature` (hex HMAC over the canonical artifact, required for
  `PRODUCTION`)

## Approval authenticity (operator-held key)

A JSON that merely says `authorized: true` is **not** sufficient for a
Production import. The Production entrypoint loads the abstract with
`load_authorization`, and a `PRODUCTION` authorization must carry a valid
HMAC-SHA256 signature produced with an operator-held key:

- key source 1: `TRADINGAI_G12_APPROVAL_HMAC_KEY` (at least 32 bytes), or
- key source 2: `TRADINGAI_G12_APPROVAL_HMAC_KEY_FILE` (regular file, mode
  `600`, at least 32 bytes, no symlink).

The key must live outside the Work BC worktree and must never be recorded in
evidence or chat. Missing key, unsigned artifact, wrong method, malformed
signature, or a signature over different bytes fail closed. The isolated test
environment remains unsigned so offline fixtures keep working; a `PRODUCTION`
artifact cannot be downgraded to `ISOLATED_TEST` because the target guard and
the environment field must agree.

Operator signing helper (run by the operator, not the agent):

```python
from backend.knowledge_hub.production_ingest import (
    APPROVAL_SIGNATURE_METHOD,
    sign_authorization_payload,
)
payload["approval_signature_method"] = APPROVAL_SIGNATURE_METHOD
payload["approval_signature"] = sign_authorization_payload(payload, key)
```

The signature covers every field except `approval_signature` and
`approval_signature_method`, serialized with sorted keys and compact
separators. Editing any approved field after signing invalidates it.

The module never creates this artifact. A prior G9/G10/G11 approval and an
isolated-test approval ledger do not satisfy it.

## Enforcement summary

- Exact canonical Production target; no path override.
- Store identity: SHA256, device, inode, schema version, integrity, record count.
- Owner/group and owner-only file and parent-directory permissions.
- No WAL/SHM/journal sidecars at Production guard time.
- Manifest hash and exact record allowlist.
- Source path provenance, source SHA256, and content SHA256.
- Re-derived Store record ID must equal the approved `STORE_RECORD_ID`.
- Trust classification is re-checked before write: `DEVELOPMENT_REPORT`,
  `AGENT_REPORTED`, authority `NONE`, access `OPERATOR`,
  `UNTRUSTED_KNOWLEDGE`, Runtime Truth `NOT_ASSERTED`,
  `UNTRUSTED_HISTORICAL`.
- One bounded transaction; rollback before commit on any error.
- Idempotent rerun skips existing records; changed content conflicts are refused.
- Post-commit integrity, record-count, and FTS consistency verification.
- Pre-import backup (Production only) with integrity and count verification.
- Audit evidence for both success and failure.
- Fail closed on missing, expired, mismatched, or unverifiable authorization.

## Entrypoints

- `run_g12_production_import(...)`: the only Production entrypoint. Binds to the
  canonical Store. This task does not call it with `apply=True`.
- `run_authorized_import(...)`: the shared contract engine used by isolated
  acceptance.
- `production_target_guard()` / `isolated_target_guard(...)`: environment-bound
  target guards.

## Offline acceptance

`tests/test_knowledge_hub_production_ingest.py` covers authorization, allowlist,
hashes, provenance, trust, schema, target identity, atomic rollback, idempotency,
FTS, reader search, Advisor/Supervisor read-only access, backup integrity, and
preservation of the existing temporary-store guard.

No test writes to the Production Store.
