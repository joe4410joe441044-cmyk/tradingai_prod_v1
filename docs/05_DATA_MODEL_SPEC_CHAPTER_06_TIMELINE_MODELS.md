
# 05_DATA_MODEL_SPEC

# Chapter 6 — Timeline Models

## 6.1 Purpose

Timeline Models は、MARKET INTELLIGENCE における市場・AI・Execution・Position の
出来事を時系列で記録・表示・Replayするための標準モデルを定義する。

Timeline は監査・デバッグ・分析・Replay の基盤であり、
過去イベントを上書きしない immutable event log を前提とする。

---

## 6.2 Timeline Philosophy

- Event は追加のみ
- 過去を書き換えない
- 全イベントは時系列で追跡可能
- Replay と同一イベントを利用する
- Position・Decision・Railway・Marker を相互参照する

---

## 6.3 Timeline Structure

```text
Timeline
 ├─ Timeline Group
 │    ├─ Timeline Event
 │    ├─ Timeline Event
 │    └─ Timeline Event
 └─ Timeline Event
```

---

## 6.4 Timeline Event

保持項目

- eventId
- eventType
- category
- severity
- timestamp
- sequence
- title
- summary
- references
- correlationId

---

## 6.5 Timeline Group

同一判断サイクルをまとめる。

保持項目

- groupId
- groupType
- state
- startTime
- endTime
- eventIds

---

## 6.6 Event Categories

- MARKET
- DETECTOR
- FEATURE
- STRATEGY
- LSTM
- LLM
- CONSENSUS
- GOVERNANCE
- EXECUTION
- ORDER
- POSITION
- RISK
- EMERGENCY
- REPLAY
- SYSTEM
- ERROR

---

## 6.7 Severity

- DEBUG
- INFO
- NOTICE
- WARNING
- HIGH
- CRITICAL

---

## 6.8 Ordering Rules

表示順序

1. eventTimestamp
2. sequence
3. createdAt
4. eventId

高速 Replay 中も順序を変更しない。

---

## 6.9 Event Relationships

Timeline Event は参照できる。

- Feature Snapshot
- Decision Chain
- Position
- Railway
- Marker
- Replay Frame

---

## 6.10 Immutable Rules

禁止事項

- Event 更新
- Event 削除
- Event 並び替え
- Event 内容書き換え

訂正は Correction Event を追加する。

---

## 6.11 Filtering

対応フィルター

- Time
- Category
- Severity
- Position
- Decision
- Replay
- Symbol

---

## 6.12 Search

検索対象

- eventId
- correlationId
- positionId
- symbol
- reasonCode
- decision

---

## 6.13 Timeline API

返却対象

- Timeline Events
- Timeline Groups
- Pagination Cursor
- Total Count

---

## 6.14 Validation

検証

- duplicate sequence
- timestamp order
- missing reference
- invalid category
- invalid severity

---

## 6.15 Review Checklist

- Event は immutable
- Group が定義される
- Replay と共通利用
- Event 順序維持
- Category 分離
- Severity 分離
- Filtering 対応
- Search 対応

---

## Chapter 6 Status

STATUS: COMPLETE
TITLE: Timeline Models
