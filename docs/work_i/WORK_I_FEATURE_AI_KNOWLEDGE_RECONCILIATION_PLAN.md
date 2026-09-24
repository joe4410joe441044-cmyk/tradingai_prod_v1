# WORK I — `feature/ai-knowledge` Reconciliation Plan

- Document: `docs/work_i/WORK_I_FEATURE_AI_KNOWLEDGE_RECONCILIATION_PLAN.md`
- Task ID: TRADINGAI-WORK-I-CANONICAL-KNOWLEDGE-EVIDENCE-CONTRACT-AND-LEGACY-BRANCH-RECONCILIATION-RESUME-1
- Status: DESIGN / READ-ONLY ASSESSMENT (no merge, no rebase, no cherry-pick, no branch change)
- Base ref: `f553439ada1e9955242b643ef246986305a45a3f` (main)
- Legacy branch: `feature/ai-knowledge` @ `b2476ffd4cf13e80d9cd602d03b0037a4eaef4f2`
- Legacy worktree: `/home/joe4410joe/tradingai_prod_v1.worktrees/ai-knowledge` (pre-existing dirty, untouched)
- Merge base: `11e6890ecf8578936a286dc79519a9819aac9405`
- Divergence: `main...feature/ai-knowledge` = 130 / 15 (branch is stale by 130 main commits)
- Related contract: `docs/work_i/WORK_I_CANONICAL_KNOWLEDGE_EVIDENCE_CONTRACT_V1.md`

## 0. Wholesale Merge Decision

**PROHIBITED / REJECTED.** A wholesale merge, rebase, or `CHERRY_PICK_WHOLE` of `feature/ai-knowledge`
is forbidden. Evidence:

- The branch is 130 commits behind main; 12 files it modified were independently modified on main
  since the merge base, several heavily: `runtime_reader.py` (main 328+ vs branch 430+),
  `browser_gateway.py` (main 54+ vs branch 342+), `prompt_builder.py` (main 57+ vs branch 166+),
  `context_builder.py`, `models.py`, `conversation_models.py`, `service.py`, `main.py`.
- `feature/ai-knowledge` is **not** an ancestor of main (merge base `11e6890`).
- Decision: reconcile **selectively** (per commit / per component below) after the canonical contract,
  never as an all-or-nothing merge.

Reuse decisions used below (required vocabulary):
`PORT_CONCEPT_ONLY`, `PORT_SELECTED_FILES`, `REIMPLEMENT_ON_CURRENT_MAIN`, `ALREADY_SUPERSEDED`,
`RETIRE`, `NEEDS_FURTHER_REVIEW`.

---

## 1. Fifteen-Commit Reconciliation (`main..feature/ai-knowledge`)

Ordered oldest → newest. "Conflict risk" judged against current main.

### 1.1 `3ed16da` — `feat(knowledge): add read-only Knowledge Core foundational registries`
- **Files:** `backend/knowledge_core/{__init__,_base,authority,component_registry,core,domain,provenance,reason_codes,runtime_semantics,source_index,system_map}.py`; `tests/test_knowledge_core.py`.
- **Responsibility:** read-only registries/vocabulary (authority classes, truth levels, source index, system map, reason codes).
- **Tests:** `tests/test_knowledge_core.py` (195).
- **Dependency:** none (pure, provider-neutral).
- **Current-main equivalent:** none (paths absent on main); main has implicit vocabulary in `backend/ai_advisor/authoritative_knowledge.py`.
- **Conflict risk:** LOW (all new files).
- **Authority risk:** LOW — declares `KnowledgeAuthority.INFORMATION_ONLY`; no mutation surface.
- **Security risk:** LOW — no network/SDK/secrets.
- **Reuse decision:** **PORT_CONCEPT_ONLY**.
- **Reason:** the vocabulary already informed the contract (truth hierarchy, authority classes, availability). Importing 2k lines wholesale is unnecessary; port the enums/registries as needed.

### 1.2 `e03d708` — `feat(knowledge): consolidate canonical knowledge loader`
- **Files:** `backend/knowledge_core/canonical_loader.py`; `backend/ai_advisor/authoritative_knowledge.py` (267); `backend/ai_advisor/knowledge.py` (22); `backend/knowledge_core/__init__.py`; `tests/test_knowledge_core_loader.py`.
- **Responsibility:** single SHA-256 hash-pinned read-only loader for allowlisted `docs/` specs.
- **Tests:** `tests/test_knowledge_core_loader.py` (374).
- **Dependency:** `knowledge_core._base`, `authority`, `provenance`.
- **Current-main equivalent:** PARTIAL — main already has hash-pinned manifest `production_knowledge_manifest` (`backend/ai_advisor/authoritative_knowledge.py:65`) loaded at `backend/main.py:852`; `knowledge.py` registry with `retrievalEnabled=False`.
- **Conflict risk:** MEDIUM — `authoritative_knowledge.py`/`knowledge.py` are branch+main shared concepts; new loader overlaps main loader.
- **Authority risk:** LOW (INFORMATION_ONLY, fail-closed HASH_MISMATCH).
- **Security risk:** LOW (no generic fs reader; only `docs/` manifest entries).
- **Reuse decision:** **REIMPLEMENT_ON_CURRENT_MAIN**.
- **Reason:** do not introduce a second canonical loader; merge the hash-pinned loader concept into main's existing `authoritative_knowledge.py` so there remains exactly one canonical document loader.

### 1.3 `1034736` — `feat(advisor): add read-only TradingAI runtime context`
- **Files:** `browser_gateway.py`, `context_builder.py`, `conversation_models.py`, `models.py`, `prompt_builder.py`, `runtime_reader.py`, `service.py`, `backend/api/ai_advisor.py`, `main.py`, `tests/test_ai_advisor_runtime_context.py`, `tests/test_ai_advisor_runtime.py`.
- **Responsibility:** live runtime context injection into Advisor.
- **Tests:** `test_ai_advisor_runtime_context.py` (781).
- **Dependency:** runtime authorities.
- **Current-main equivalent:** YES — main independently has `runtime_reader.read_runtime_scalars` (`runtime_reader.py:380`) and `context_builder.build_runtime_context` (`:235`), wired in `main.py`.
- **Conflict risk:** HIGH — same files, divergent implementations.
- **Authority risk:** LOW (read-only).
- **Security risk:** LOW.
- **Reuse decision:** **ALREADY_SUPERSEDED**.
- **Reason:** main already provides read-only runtime context; adopting the branch variant would duplicate/conflict and re-open an already-integrated surface.

### 1.4 `61f621d` — `feat(advisor): add persistent conversation memory`
- **Files:** `backend/ai_advisor/conversation_store.py` (648, NEW); `browser_gateway.py` (305); `main.py`; frontend `AdvisorConversation.jsx`, `advisorBrowserGatewayClient.js`, `advisorConversationModel.js` (+tests); `tests/test_ai_advisor_conversation_memory.py`.
- **Responsibility:** dedicated server-side, bounded, redacted SQLite conversation memory (CONTEXT_ONLY).
- **Tests:** `test_ai_advisor_conversation_memory.py` (1036) + frontend tests.
- **Dependency:** `context_builder.sanitize_text`, `conversation_models`.
- **Current-main equivalent:** NONE — audit confirms advisor history MISSING (`browser_gateway.py:421` empty).
- **Conflict risk:** MEDIUM — store is new; gateway/main/frontend wiring conflicts.
- **Authority risk:** LOW — explicitly CONTEXT_ONLY, never authoritative.
- **Security risk:** LOW — redacts secrets/paths, operator-scoped, bounded.
- **Reuse decision:** **PORT_SELECTED_FILES** (`conversation_store.py` + its tests), wiring **REIMPLEMENT_ON_CURRENT_MAIN**.
- **Reason:** directly closes a proven gap; the store is self-contained and safe; the gateway/frontend wiring must be rebuilt on current main.

### 1.5 `45bbfea` — `feat(advisor): add unified trading trace linkage`
- **Files:** `backend/runtime/unified_trace.py` (900, NEW); `backend/ai_advisor/historical_trace_evidence.py` (364, NEW); `advisor_service.py`, `context_builder.py`, `conversation_models.py`, `prompt_builder.py`, `prompt_models.py`, `service_models.py`; `tests/test_d5_unified_trade_trace.py`, `tests/test_d5_ai_advisor_historical_trace.py`.
- **Responsibility:** INFORMATION_ONLY assembled view linking existing `TradingTraceStore` evidence (no second history).
- **Tests:** `test_d5_unified_trade_trace.py` (313), `test_d5_ai_advisor_historical_trace.py` (216).
- **Dependency:** `backend/runtime/trading_trace.py` (STAGES, TradingTraceStore, sanitize_metadata).
- **Current-main equivalent:** NONE for the unified view; main has the underlying trace store only.
- **Conflict risk:** MEDIUM (new files) / HIGH (prompt/context/browser wiring).
- **Authority risk:** LOW — `INFORMATION_ONLY`, read-only; never creates a trade.
- **Security risk:** LOW — allowlisted node types, bounded, provenance preserved.
- **Reuse decision:** **PORT_SELECTED_FILES** (`unified_trace.py`, `historical_trace_evidence.py` + tests), wiring **REIMPLEMENT_ON_CURRENT_MAIN**.
- **Reason:** the linkage view is the central Advisor retrieval enabler and explicitly avoids a duplicate store; its prompt wiring must be rebuilt on current main.

### 1.6 `2bed0f4` — `feat(supervisor): add deterministic specialist architecture`
- **Files:** `backend/supervisor/specialists/{__init__,bounded_context,common,contracts,execution,master,money_management,severity,strategy,system_health}.py`; `backend/supervisor/__init__.py`; `tests/test_supervisor_specialist_architecture.py`.
- **Responsibility:** deterministic, provider-neutral, observation-only specialist findings + fail-closed severity ladder.
- **Tests:** `test_supervisor_specialist_architecture.py` (495).
- **Dependency:** existing `backend/supervisor/contracts.py` (`SupervisorContract`, `Freshness`).
- **Current-main equivalent:** NONE (dir absent on main); main has shadow evaluators but no specialists.
- **Conflict risk:** LOW (new dir) / LOW-MEDIUM (`supervisor/__init__.py`).
- **Authority risk:** LOW — `READ_ONLY_ANALYSIS`; no mutation surface.
- **Security risk:** LOW.
- **Reuse decision:** **PORT_SELECTED_FILES**.
- **Reason:** additive to the existing Supervisor shadow layer; fail-closed semantics align with the contract and the audit's recommended extension.

### 1.7 `3bdfad1` — `test(supervisor): lock specialist severity precedence`
- **Files:** `tests/test_supervisor_specialist_architecture.py` (+75).
- **Responsibility:** regression-lock the fail-closed severity ordering.
- **Tests:** same file.
- **Dependency:** `2bed0f4`.
- **Current-main equivalent:** NONE.
- **Conflict risk:** LOW.
- **Authority risk:** NONE.
- **Security risk:** NONE.
- **Reuse decision:** **PORT_SELECTED_FILES** (with `2bed0f4`).
- **Reason:** test-only; travels with the specialists port.

### 1.8 `c4a0507` — `feat(knowledge): add provenance and drift detection`
- **Files:** `backend/knowledge_core/drift.py` (891, NEW); `knowledge_core/provenance.py` (additive); `knowledge_core/__init__.py`; `backend/ai_advisor/drift_context.py` (257, NEW); `backend/supervisor/drift_surface.py` (149, NEW); `tests/test_d7_provenance_drift.py`.
- **Responsibility:** deterministic read-only provenance/drift views; never rewrites a layer.
- **Tests:** `test_d7_provenance_drift.py` (664).
- **Dependency:** `knowledge_core._base/authority/provenance`, D5/D6 provenance contracts.
- **Current-main equivalent:** NONE.
- **Conflict risk:** LOW (new files).
- **Authority risk:** LOW — INFORMATION_ONLY throughout.
- **Security risk:** LOW — no network/SDK; no source mutation.
- **Reuse decision:** **PORT_SELECTED_FILES**.
- **Reason:** needed for `HISTORICAL`/`SUPERSEDED` classification and truth-preserving projections; self-contained.

### 1.9 `5a14e61` — `feat(knowledge): add experience investigation and validation lifecycle`
- **Files:** `backend/knowledge_evolution/{__init__,_base,advisor_projection,authority,experience,finding,human_review,hypothesis,investigation,knowledge,pattern,supervisor_projection,validation}.py` (all NEW); `tests/test_d8_experience_evolution.py`.
- **Responsibility:** EVIDENCE_ONLY experience memory + ANALYSIS_ONLY investigation/validation + projection objects.
- **Tests:** `test_d8_experience_evolution.py` (1013).
- **Dependency:** `knowledge_core` provenance/authority; `unified_trace`.
- **Current-main equivalent:** NONE.
- **Conflict risk:** LOW (new files).
- **Authority risk:** LOW — strict non-operational ladder; `assert_no_mutation` guard.
- **Security risk:** LOW.
- **Reuse decision:** **PORT_SELECTED_FILES**.
- **Reason:** the knowledge-candidate lifecycle model required by the contract; read-only, bounded, human-review gated.

### 1.10 `3c4d02a` — `feat(advisor): wire unified trace evidence into runtime conversation`
- **Files:** `browser_gateway.py`, `historical_trace_evidence.py`, `main.py`, `tests/test_d9b_advisor_trace_wiring.py`.
- **Responsibility:** runtime wiring of trace evidence into Advisor conversation.
- **Tests:** `test_d9b_advisor_trace_wiring.py` (518).
- **Dependency:** `45bbfea`, `61f621d`.
- **Current-main equivalent:** NONE (wiring absent).
- **Conflict risk:** HIGH — `browser_gateway.py`/`main.py` diverged heavily.
- **Authority risk:** LOW.
- **Security risk:** LOW.
- **Reuse decision:** **REIMPLEMENT_ON_CURRENT_MAIN**.
- **Reason:** wiring must be rebuilt against current `browser_gateway.py`/`main.py`; the underlying `historical_trace_evidence.py` is ported in `45bbfea`.

### 1.11 `8216bfb` — `test(advisor): assert contextInput/contextEnvelope trace evidence invariant`
- **Files:** `tests/test_d9b_advisor_trace_wiring.py` (+23).
- **Responsibility:** invariant test for the trace wiring.
- **Tests:** same file.
- **Dependency:** `3c4d02a`.
- **Current-main equivalent:** NONE.
- **Conflict risk:** LOW (test) but tied to reimplemented wiring.
- **Authority risk:** NONE.
- **Security risk:** NONE.
- **Reuse decision:** **REIMPLEMENT_ON_CURRENT_MAIN**.
- **Reason:** the invariant must be asserted against the reimplemented wiring, not the branch file.

### 1.12 `27cc48c` — `feat(knowledge): add durable knowledge persistence foundation`
- **Files:** `backend/knowledge_evolution/store.py` (1979, NEW; grows to 2125); `tests/test_d9f_knowledge_persistence.py` (896).
- **Responsibility:** durable, fail-closed SQLite knowledge persistence (PERSISTENCE_ONLY); append-only Human Review; deterministic-id conflict detection.
- **Tests:** `test_d9f_knowledge_persistence.py` (896).
- **Dependency:** `knowledge_core` serialization/fingerprint; `knowledge_evolution` domain objects.
- **Current-main equivalent:** NONE; audit notes main has no persistent knowledge store.
- **Conflict risk:** LOW (new file) / MEDIUM (coupling to large dependency set).
- **Authority risk:** LOW by design (PERSISTENCE_ONLY; separate DB; no runtime control).
- **Security risk:** MEDIUM-REVIEW — largest new component; must re-verify no secret leakage, DB isolation, bounded reads, trigger enforcement.
- **Reuse decision:** **PORT_SELECTED_FILES** (store + supporting domain modules), subject to a dedicated security/isolation review before port.
- **Reason:** it is the single durable knowledge authority the contract requires; adopting it prevents a duplicate store. Port only after the review; never alongside a second knowledge store.

### 1.13 `18d403d` — `feat(knowledge): expose knowledge and human review backend api`
- **Files:** `backend/knowledge_evolution/service.py` (696, NEW); `backend/knowledge_evolution/store.py` (+146); `backend/api/knowledge.py` (404, NEW); `main.py`; `tests/test_d9c_knowledge_api.py`.
- **Responsibility:** service layer + operator-session-protected API for the lifecycle; server-side reviewer identity; no runtime mutation.
- **Tests:** `test_d9c_knowledge_api.py` (1105).
- **Dependency:** `27cc48c`, `5a14e61`.
- **Current-main equivalent:** NONE.
- **Conflict risk:** MEDIUM (`main.py` mount) / LOW (new files).
- **Authority risk:** LOW — reviewer identity from trusted operator session; subject fingerprint server-side.
- **Security risk:** MEDIUM-REVIEW — write endpoints exist but only to the knowledge DB; must confirm they cannot reach runtime/config/authority; must confirm auth.
- **Reuse decision:** **PORT_SELECTED_FILES** (`service.py`, `api/knowledge.py`) + `main.py` wiring **REIMPLEMENT_ON_CURRENT_MAIN**.
- **Reason:** provides the human-review promotion boundary; router mount must be re-added on current main.

### 1.14 `9111890` — `feat(advisor): integrate knowledge evolution runtime context`
- **Files:** `backend/ai_advisor/knowledge_context.py` (497, NEW); `advisor_service.py`, `browser_gateway.py`, `context_builder.py`, `conversation_models.py`, `prompt_builder.py`, `prompt_models.py`, `service_models.py`, `main.py`; `tests/test_d9d_advisor_knowledge_runtime.py`.
- **Responsibility:** bounded KNOWLEDGE_EVOLUTION prompt layer for Advisor (separate from current runtime and historical evidence).
- **Tests:** `test_d9d_advisor_knowledge_runtime.py` (949).
- **Dependency:** `27cc48c`, `18d403d`, `45bbfea`, `5a14e61`.
- **Current-main equivalent:** NONE.
- **Conflict risk:** MEDIUM (new file) / HIGH (prompt/context wiring).
- **Authority risk:** LOW — INFORMATION_ONLY, READ_ONLY, provider-neutral.
- **Security risk:** LOW — allowlisted, bounded, no raw rows/SQL.
- **Reuse decision:** **PORT_SELECTED_FILES** (`knowledge_context.py` + tests), wiring **REIMPLEMENT_ON_CURRENT_MAIN**.
- **Reason:** delivers the labeled knowledge projection to the Advisor; the projection file is self-contained.

### 1.15 `b2476ff` — `feat(ai-advisor): inject authoritative runtime context`
- **Files:** `context_builder.py`, `conversation_models.py`, `models.py`, `prompt_builder.py`, `runtime_reader.py` (256), `service.py`, `tests/test_ai_advisor_runtime_injection.py`.
- **Responsibility:** authoritative runtime context injection into the Advisor.
- **Tests:** `test_ai_advisor_runtime_injection.py` (399).
- **Dependency:** runtime authorities.
- **Current-main equivalent:** PARTIAL/YES — main has authoritative knowledge loader (`main.py:852`) + runtime reader; naming/envelope may differ.
- **Conflict risk:** HIGH — same files as main's independent evolution.
- **Authority risk:** LOW.
- **Security risk:** LOW.
- **Reuse decision:** **NEEDS_FURTHER_REVIEW**.
- **Reason:** determine whether current main already covers the authoritative-injection intent; if a field-level gap remains, reimplement only that gap on current main rather than import.

### 1.16 Commit summary

| # | SHA | Subject (short) | Reuse decision |
|---|---|---|---|
| 1 | `3ed16da` | Knowledge Core registries | PORT_CONCEPT_ONLY |
| 2 | `e03d708` | Canonical knowledge loader | REIMPLEMENT_ON_CURRENT_MAIN |
| 3 | `1034736` | Advisor runtime context | ALREADY_SUPERSEDED |
| 4 | `61f621d` | Advisor conversation memory | PORT_SELECTED_FILES |
| 5 | `45bbfea` | Unified trace linkage | PORT_SELECTED_FILES |
| 6 | `2bed0f4` | Supervisor specialists | PORT_SELECTED_FILES |
| 7 | `3bdfad1` | Specialist severity test | PORT_SELECTED_FILES |
| 8 | `c4a0507` | Provenance + drift | PORT_SELECTED_FILES |
| 9 | `5a14e61` | Experience/Investigation/Validation | PORT_SELECTED_FILES |
| 10 | `3c4d02a` | Wire trace into conversation | REIMPLEMENT_ON_CURRENT_MAIN |
| 11 | `8216bfb` | Trace evidence invariant test | REIMPLEMENT_ON_CURRENT_MAIN |
| 12 | `27cc48c` | Durable knowledge persistence | PORT_SELECTED_FILES (post security review) |
| 13 | `18d403d` | Knowledge + human review API | PORT_SELECTED_FILES (wiring reimplemented) |
| 14 | `9111890` | Advisor knowledge evolution context | PORT_SELECTED_FILES (wiring reimplemented) |
| 15 | `b2476ff` | Authoritative runtime injection | NEEDS_FURTHER_REVIEW |

No commit is classified `CHERRY_PICK_WHOLE`; none is `RETIRE` outright. `RETIRE` remains available for
any component failing the security/isolation review.

---

## 2. Component-Level Evaluation

| Component | Files (branch) | Decision | Reason |
|---|---|---|---|
| `knowledge_core` | `backend/knowledge_core/*` | PORT_CONCEPT_ONLY | Read-only foundational vocabulary; concepts already reflected in the contract; avoid importing 2k lines blind. |
| `canonical_loader` | `knowledge_core/canonical_loader.py` | REIMPLEMENT_ON_CURRENT_MAIN | Do not create a second loader; merge into main's `authoritative_knowledge.py`. |
| `provenance` | `knowledge_core/provenance.py` | PORT_SELECTED_FILES | Small, truth-preserving `ProvenanceRecord`; reused by store/drift. |
| `drift` | `knowledge_core/drift.py` | PORT_SELECTED_FILES | Deterministic read-only drift assessment; needed for `SUPERSEDED`/`HISTORICAL`. |
| knowledge_evolution store | `knowledge_evolution/store.py` | PORT_SELECTED_FILES (post security review) | Single durable knowledge authority; must not be duplicated. |
| experience lifecycle | `knowledge_evolution/{experience,finding,pattern,hypothesis,knowledge,human_review}.py` | PORT_SELECTED_FILES | EVIDENCE/ANALYSIS-only domain objects with deterministic IDs. |
| investigation | `knowledge_evolution/investigation.py` | PORT_SELECTED_FILES | Bounded ANALYSIS_ONLY evidence selection. |
| validation | `knowledge_evolution/validation.py` | PORT_SELECTED_FILES | Deterministic non-binary validation; no fabricated pass/fail. |
| advisor projection | `knowledge_evolution/advisor_projection.py` | PORT_SELECTED_FILES | Labeled, bounded, READ_ONLY projection (no truth flattening). |
| supervisor projection | `knowledge_evolution/supervisor_projection.py` | PORT_SELECTED_FILES | Bounded READ_ONLY_ANALYSIS summary; no investigation authority. |
| conversation_store | `ai_advisor/conversation_store.py` | PORT_SELECTED_FILES | Fills proven advisor-history gap; CONTEXT_ONLY; secret-redacting; operator-scoped. |
| knowledge_context | `ai_advisor/knowledge_context.py` | PORT_SELECTED_FILES | Bounded KNOWLEDGE_EVOLUTION prompt layer; no second persistence. |
| historical_trace_evidence | `ai_advisor/historical_trace_evidence.py` | PORT_SELECTED_FILES | Bounded HISTORICAL_EVIDENCE view; preserves reason codes/provenance. |
| unified_trace | `runtime/unified_trace.py` | PORT_SELECTED_FILES | INFORMATION_ONLY linkage view; explicitly no second trade history. |
| supervisor specialists | `supervisor/specialists/*`, `supervisor/drift_surface.py` | PORT_SELECTED_FILES | Additive deterministic read-only analysis; fail-closed severity. |
| knowledge API | `api/knowledge.py` + `knowledge_evolution/service.py` | PORT_SELECTED_FILES (router wiring reimplemented) | Operator-auth lifecycle/human-review boundary; no runtime mutation. |

---

## 3. Single Source Decisions

| Domain | Canonical single source | WORK I rule |
|---|---|---|
| Trade history | Stage 13 `logs/runtime/parameter_performance.jsonl` (`parameter_performance.py:361`) | read/join only; never a second trade store |
| Performance | `compute_metrics` (`parameter_performance_read.py:69`) | reuse; no second metrics authority |
| Parameter Revision | `ParameterRevisionArchive` (`revision_archive.py:80`) | reuse; no parallel revision store |
| MM history | `loss_limit_state.json` + `money_management_timeline.jsonl` (`loss_persistence_adapter.py`, `timeline.py`) | reuse; no second MM store |
| Governance evidence | `governance_runtime` (in-memory, `:10,:36`) | **do not duplicate**; persist only via separately-approved bounded task |
| Supervisor events | `logs/runtime/supervisor_audit.sqlite3` (`audit_store.py`) | reuse |
| Advisor conversation history | new `conversation_store.py` (ported) as CONTEXT_ONLY | not authority |
| Knowledge Candidate store | ported `knowledge_evolution/store.py` (single) | **one** knowledge authority only |
| Cycle evidence | new canonical envelope view over existing stores | derived view; no new raw store |
| Trading trace | `TradingTraceStore` (`trading_trace.py:408`) | reuse writer; make reader restart-safe |
| API | existing routers + additive read routers | extend, never fork |
| UI state | frontend state (incl. `localStorage`) | presentation-only; never authority |

---

## 4. `feature/ai-knowledge` Integration Sequence (recommended, not executed here)

1. Land the canonical contract (this task) as the design authority.
2. **P0-1**: restart-safe, bounded trace reader (see § 5) — does not depend on branch code.
3. **P0-2**: canonical cycle-evidence envelope writer over existing Stage 13 + trace + MM + revision
   (additive, versioned; no new store).
4. **P0-3**: governance decision durability (bounded, read-only evidence), separately approved.
5. Port read-only components (`unified_trace`, `historical_trace_evidence`, `provenance`, `drift`,
   `knowledge_core` concepts) with reimplemented wiring on current main.
6. Port `knowledge_evolution` domain + store after the security/isolation review; mount
   `api/knowledge` with operator auth.
7. Port `conversation_store` and wire Advisor; port supervisor specialists.
8. Reimplement prompt/gateway wiring (`browser_gateway`, `prompt_builder`, `context_builder`,
   `main.py`) last, against current main.
9. Delete/retire only after all selected files are in and reviewed; the branch is never merged
   wholesale.

---

## 5. Next Minimal Implementation Task

- **Task ID (proposed):** `TRADINGAI-WORK-I-P0-1-RESTART-SAFE-CYCLE-EVIDENCE-CAPTURE-1`
- **Purpose:** make the canonical evidence retrieval real enough for `WORK_AA_REAL_E2E_001` without
  creating any new store or authority.
- **Scope (implementation, separately approved):**
  1. Restart-safe, bounded, indexed reader for `logs/runtime/trading_e2e_trace.jsonl` (33.6 GB) that
     never fully memory-loads and never creates a second trade history.
  2. Additive, versioned canonical cycle-evidence envelope writer that **joins existing** Stage 13 +
     trace + MM timeline + parameter revision records by `cycle_id`/`trade_id`/`correlation_id`.
  3. Explicit availability states (§ F) for every not-yet-captured field; no invented values.
  4. Provenance fields: `task_id`, `commit_sha`, `acceptance_id`.
- **Reused implementation:** `parameter_performance.py`, `trade_history_read.py`,
  `parameter_performance_read.py`, `revision_archive.py`, MM `timeline.py`/`loss_persistence_adapter.py`,
  `trading_trace.py`, `f553439` `risk_percent_authority.py` / `spread_unit_classification.py` /
  `persist-baseline`.
- **Explicit non-goals:** no new trade/revision/knowledge store; no MM/Governance/Execution authority
  change; no Advisor/Supervisor authority change; no LIVE arm; no order.
- **Dependencies:** the contract document in this worktree.
- **Validation for that task:** unit tests for envelope serialization + availability semantics +
  restart-safe reader bounds; no live/runtime writes.

---

## 6. Validation Performed For This Plan

- `git merge-base --is-ancestor` (branch not ancestor of main); `git rev-list --left-right --count
  main...feature/ai-knowledge` = 130 / 15.
- Per-commit `git show --stat` for all 15 commits; `git diff --name-status main...feature/ai-knowledge`.
- Main-touch overlap intersection and per-file numstat (main vs branch) for shared files.
- Existence checks: all branch-only component paths absent on main.
- READ-ONLY reads of selected branch files via the existing worktree (authority, provenance,
  projections, store, trace, conversation store, specialists, API).

No merge/rebase/cherry-pick/commit/push; legacy worktree and branch untouched.
