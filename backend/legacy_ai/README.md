# Legacy Trading AI Prototype

## Status

- ARCHIVED
- NOT_ACTIVE
- NOT_PRODUCTION_AUTHORITY

## Historical Purpose

This prototype experimented with BUY, SELL, and HOLD review around Python
Strategy candidates.  It is preserved for audit and possible offline research;
it is not part of the production trading mainline.

## Actual Implementation

- `LSTMModel` was not a trained LSTM. It averaged the last five entries of a
  hand-built feature vector and applied fixed thresholds.
- `LLMEngine` did not call an external LLM. It was a deterministic rule engine.
- `TradeBrain` required the heuristic and rule engine to agree.
- `AIPipeline`, `FeatureEngine`, `RuntimeAdapter`, `RuntimeState`, and
  `FeatureVector` were prototype-specific orchestration and data support.
- `AIRiskFilter` was a fixed-score rule used by a dormant development
  `TradeCore`; its logger/router/schema helpers are archived alongside it.
- `CapitalProtectionAI` was a deterministic loss-streak switch, not AI.
- `standalone_api.py` was an unmounted standalone status prototype.
- `history/` preserves previously ignored `.bak_*` development snapshots as
  trackable `*.snapshot.py` files;
  their original import statements are documentary and are never executed.

## Why Archived

- No trained model was connected.
- No external LLM was connected.
- Feature authority diverged from the normalized Strategy contract.
- Feature scales and duplicated inputs made the heuristic restrictive.
- AI executed before Strategy while being presented as a Strategy reviewer.

## Current Mainline

Legacy AI is disconnected from production. Trading AI is explicitly `OFF` and
its implementation status is `NOT_INSTALLED`.

```text
Market / Order Book
→ Python Detectors and Feature Builder
→ Python Strategy
→ Money Management
→ Governance
→ Execution
```

No Legacy heuristic or rule engine is used as a fallback.

## Future Reuse

This directory is not a deletion target. Its code may inform a future ML
predictor, optional Trading AI reviewer, decision model, offline research tool,
or feature experiment after a new authority and input contract are designed.

## Important

Do not describe this code as a trained AI, LSTM, or LLM. Production modules
must not import `backend.legacy_ai`. Only archival tests and offline research
tools may do so.
