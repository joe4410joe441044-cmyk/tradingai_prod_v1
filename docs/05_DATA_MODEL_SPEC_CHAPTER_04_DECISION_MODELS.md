
# 05_DATA_MODEL_SPEC

# Chapter 4 — Decision Models

## 4.1 Purpose

Decision Models は MARKET INTELLIGENCE の判断チェーンを定義する。

```
Feature Snapshot
    ↓
Python Strategy
    ↓
LSTM
    ↓
LLM
    ↓
Consensus
    ↓
Governance
    ↓
Execution
```

各段階は独立した Entity を持ち、前段の結果を上書きしない。

---

## 4.2 Decision Principles

- Python が市場特徴を解析する。
- Strategy は最初の売買候補を生成する。
- LSTM は時系列補助評価を行う。
- LLM は総合判断を行う。
- Consensus は複数判断を統合する。
- Governance は最終安全判定を行う。
- Execution は注文実行のみ担当する。

---

## 4.3 Shared Decision Model

共通フィールド

- id
- featureSnapshotId
- inputReferences
- direction
- confidence
- reasoning
- suppressionReason
- processingTimeMs
- modelVersion
- createdAt

---

## 4.4 Python Strategy

責務

- BUY / SELL / HOLD 候補生成
- executionAllowed 初期判定
- suppressionReason
- deterministic 処理

出力

```
BUY
SELL
HOLD
```

---

## 4.5 LSTM Model

責務

- 時系列補助評価
- 継続性
- モメンタム維持
- ノイズ低減

出力

- direction
- confidence
- persistenceScore

---

## 4.6 LLM Model

責務

- Feature と Strategy を統合
- 相反証拠を評価
- 最終 AI 判断

保持

- promptVersion
- modelIdentifier
- rawResponse
- parsedResponse
- validationResult
- tokenUsage
- latencyMs

---

## 4.7 Consensus

入力

- Strategy
- LSTM
- LLM

保持

- finalDirection
- confidence
- agreementScore
- disagreementReason

Consensus は各モデルを書き換えない。

---

## 4.8 Governance

責務

- 安全判定
- 実行可否

状態

```
ALLOWED
BLOCKED
UNKNOWN
```

保持

- blockReason
- policyVersion

---

## 4.9 Execution Decision

Execution は判断を作らない。

保持

- submitted
- acknowledged
- filled
- rejected
- executionResult

---

## 4.10 Decision Chain

```
Feature Snapshot
→ Strategy
→ LSTM
→ LLM
→ Consensus
→ Governance
→ Execution
```

全段階は trace 可能である。

---

## 4.11 Direction Enum

```
BUY
SELL
HOLD
UNKNOWN
```

---

## 4.12 Confidence

内部表現

0.0〜1.0

UI

0〜100%

---

## 4.13 Suppression

例

- LOW_LIQUIDITY
- HIGH_SPREAD
- LOW_CONFIDENCE
- GOVERNANCE_BLOCK

---

## 4.14 Validation

- Feature Snapshot 必須
- direction 必須
- version 必須
- malformed response 拒否

---

## 4.15 Review Checklist

- Decision Chain が分離されている
- Governance が最上位
- Execution は判断しない
- 全 Decision が trace 可能
- HOLD を勝手に BUY に昇格しない
- Version 管理される

---

## Chapter 4 Status

STATUS: COMPLETE
TITLE: Decision Models
