
# 05_DATA_MODEL_SPEC

# Chapter 7 — Inspector Models

## 7.1 Purpose

Inspector は、MARKET INTELLIGENCE 内の任意の Entity を詳細に解析・監査するための
読み取り専用モデルである。

Inspector は市場データ・AI判断・Execution・Position・Replay の根拠を
一画面で確認できることを目的とする。

---

## 7.2 Design Principles

- Read Only
- Entity を変更しない
- Authoritative Data を表示する
- Timeline / Railway / Replay と連携する
- 相互参照を提供する

---

## 7.3 Supported Entities

- Feature Snapshot
- Strategy Decision
- LSTM Decision
- LLM Decision
- Consensus
- Governance
- Execution
- Position
- Timeline Event
- Railway Cycle
- Marker

---

## 7.4 Inspector Layout

```text
Header
 ├─ Entity Summary
 ├─ State
 ├─ Timestamp

Body
 ├─ Properties
 ├─ References
 ├─ Timeline
 ├─ Railway
 ├─ Raw Data
 ├─ Validation
 └─ Related Entities
```

---

## 7.5 Entity Summary

保持項目

- entityId
- entityType
- state
- createdAt
- updatedAt
- source
- schemaVersion

---

## 7.6 Properties Panel

表示対象

- Core Fields
- Domain Fields
- Metrics
- Confidence
- Risk
- Status

---

## 7.7 References Panel

表示対象

- Parent Entity
- Child Entities
- Related Timeline
- Related Position
- Related Replay
- Related Marker

---

## 7.8 Validation Panel

表示

- Validation Result
- Missing Fields
- Unknown State
- Freshness
- Schema Version

---

## 7.9 Raw Data

Raw JSON を表示可能。

- Pretty Print
- Collapse
- Copy

Raw Data は編集不可。

---

## 7.10 Inspector State

```
READY
LOADING
NOT_FOUND
PARTIAL
ERROR
```

---

## 7.11 Navigation

対応

- Position → Timeline
- Timeline → Railway
- Railway → Decision
- Decision → Feature Snapshot
- Marker → Position
- Replay → Frame

---

## 7.12 API Model

返却

- entity
- references
- validation
- relatedEntities
- rawData

---

## 7.13 Validation

確認

- missing entity
- invalid reference
- stale entity
- unsupported schema
- unknown state

---

## 7.14 Review Checklist

- Read Only
- Entity 編集不可
- Raw JSON 表示
- Validation 表示
- 相互参照可能
- Timeline 連携
- Railway 連携
- Replay 連携

---

## Chapter 7 Status

STATUS: COMPLETE
TITLE: Inspector Models
