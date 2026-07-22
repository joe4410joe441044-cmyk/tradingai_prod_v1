
# 05_DATA_MODEL_SPEC

# Chapter 3 — Feature Snapshot

## 3.1 Purpose

Feature Snapshot は、Python Detector 群が市場から抽出した特徴量を、
AI・Strategy・Replay・Timeline・Inspector が共通利用するための
唯一の authoritative 市場特徴モデルである。

Feature Snapshot は以下を満たす。

- Detector の生データを統合する
- Strategy の唯一の入力となる
- LSTM / LLM の共通入力となる
- Replay で完全再現できる
- Timeline / Railway から参照できる
- Frontend は再計算しない

---

## 3.2 Snapshot Domains

Feature Snapshot は最低限以下の Domain を持つ。

- Order Book
- Recent Trades
- Liquidity
- Buy / Sell Pressure
- Momentum
- Volatility
- Spread
- Absorption
- Fake Pressure
- Iceberg
- Spoofing
- Market Context
- Detector Health
- Feature Freshness

---

## 3.3 Core Model

```json
{
  "id":"fs_01...",
  "symbol":"XRPUSDT",
  "exchange":"KUCOIN_FUTURES",
  "snapshotTimestamp":"2026-07-19T05:42:31.482Z",
  "orderBook":{},
  "recentTrades":{},
  "liquidity":{},
  "pressure":{},
  "momentum":{},
  "volatility":{},
  "spread":{},
  "absorption":{},
  "spoofing":{},
  "iceberg":{},
  "marketContext":{},
  "freshness":{
      "state":"FRESH",
      "ageMs":18
  }
}
```

---

## 3.4 Order Book Domain

保持対象例

- Top N Bid
- Top N Ask
- Mid Price
- Spread
- Best Bid
- Best Ask
- Total Bid Volume
- Total Ask Volume
- Imbalance
- Book Update Sequence

---

## 3.5 Recent Trades Domain

保持対象例

- Last Trade
- Trade Count
- Buy Market Volume
- Sell Market Volume
- Average Size
- VWAP
- Delta

---

## 3.6 Liquidity Domain

保持対象例

- Liquidity Score
- Bid Depth
- Ask Depth
- Large Wall Count
- Thin Book Detection

Score は 0.0〜1.0 を標準とする。

---

## 3.7 Pressure Domain

保持対象例

- Buy Pressure
- Sell Pressure
- Net Pressure
- Pressure Bias
- Pressure Confidence

---

## 3.8 Momentum Domain

保持対象例

- Momentum Score
- Persistence
- Acceleration
- Direction

---

## 3.9 Volatility Domain

保持対象例

- Current Volatility
- Short Window
- Long Window
- Volatility State

---

## 3.10 Spread Domain

保持対象例

- Current Spread
- Average Spread
- Spread Bps
- Spread State

---

## 3.11 Detector Domains

Detectorごとに以下を保持する。

- detectorName
- detectorVersion
- state
- score
- confidence
- evidence
- processingTimeMs

対象

- Absorption
- Fake Pressure
- Spoofing
- Iceberg

---

## 3.12 Market Context

例

- Session
- Trend
- Range
- Regime
- Risk Level

---

## 3.13 Freshness

```text
FRESH
AGING
STALE
EXPIRED
UNKNOWN
```

---

## 3.14 Feature Health

Detectorごとに

- READY
- DEGRADED
- FAILED
- DISABLED

を保持する。

---

## 3.15 Relationships

Feature Snapshot は以下へ参照される。

- Strategy Decision
- LSTM
- LLM
- Consensus
- Railway
- Timeline
- Replay

---

## 3.16 Validation

必須

- symbol
- timestamp
- freshness
- detectorVersion

異常

- symbol mismatch
- stale snapshot
- detector failure
- sequence gap

---

## 3.17 Review Checklist

- Feature Snapshot は唯一の市場特徴モデル
- Frontend は再計算しない
- Detector Domain が分離されている
- Freshness を保持する
- Replay 再現可能
- Strategy 入力と一致する
- Version 管理される

---

## Chapter 3 Status

STATUS: COMPLETE
TITLE: Feature Snapshot
