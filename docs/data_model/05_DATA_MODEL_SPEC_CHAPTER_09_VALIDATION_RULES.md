
# 05_DATA_MODEL_SPEC

# Chapter 9 — Validation Rules

## 9.1 Purpose

Validation Rules は、MARKET INTELLIGENCE の全データモデルに対して
整合性・安全性・再現性を保証するための共通検証規則を定義する。

Validation は Fail Closed を基本方針とする。

---

## 9.2 Validation Layers

1. Schema Validation
2. Field Validation
3. Enum Validation
4. Relationship Validation
5. State Validation
6. Time Validation
7. Business Validation
8. Replay Validation
9. API Validation

---

## 9.3 Required Field Validation

必須項目例

- id
- entityType
- schemaVersion
- createdAt
- context
- source

必須項目欠落時は Validation Error とする。

---

## 9.4 Enum Validation

対象

- Direction
- State
- Severity
- Category
- Marker Type

未知値は UNKNOWN として扱うか、仕様上必須の場合はエラーとする。

---

## 9.5 Relationship Validation

検証対象

- Position → Timeline
- Timeline → Railway
- Railway → Decision
- Decision → Feature Snapshot
- Marker → Position

参照切れは INVALID_REFERENCE とする。

---

## 9.6 Time Validation

検証

- createdAt <= updatedAt
- openedAt <= closedAt
- startedAt <= completedAt
- Timestamp の逆転禁止

---

## 9.7 State Validation

例

- CLOSED Position は quantity = 0
- OPEN Position は quantity > 0
- BLOCKED Governance は Execution 不可
- Replay は readOnly

---

## 9.8 Business Validation

例

- Symbol 一致
- Exchange 一致
- CorrelationId 一致
- Replay Context 一致

---

## 9.9 Replay Validation

Replay では

- Frame 欠損
- Cursor 範囲外
- Event 順序逆転
- Snapshot 欠落

を検出する。

---

## 9.10 Freshness Validation

状態

- FRESH
- AGING
- STALE
- EXPIRED
- UNKNOWN

STALE 以上は警告または Fail Closed の対象。

---

## 9.11 Error Codes

代表例

- INVALID_SCHEMA
- INVALID_STATE
- INVALID_REFERENCE
- INVALID_TIMESTAMP
- INVALID_SEQUENCE
- SYMBOL_MISMATCH
- STALE_DATA
- UNKNOWN_STATE
- REPLAY_OUT_OF_RANGE

---

## 9.12 Validation Result Model

```json
{
  "valid": true,
  "errors": [],
  "warnings": [],
  "checkedAt": "2026-07-19T05:42:31.482Z"
}
```

---

## 9.13 API Requirements

Validation Result は

- Inspector
- Replay
- Timeline
- Railway

から参照可能とする。

---

## 9.14 Review Checklist

- 必須項目検証
- Enum 検証
- State 検証
- Time 検証
- Relationship 検証
- Replay 検証
- Freshness 検証
- Error Code 定義
- Fail Closed 方針

---

## Chapter 9 Status

STATUS: COMPLETE
TITLE: Validation Rules
