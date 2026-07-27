# TradingAI

# Money Management Master Specification

**Document Name:** `01_Money_Management_Master_Specification.md`

**Version:** 1.0

**Status:** Official Master Specification

------------------------------------------------------------------------

# Chapter 0 --- Core Principles

## 0.1 Purpose

TradingAI Money Management の目的は、単に利益を最大化することではない。

また、資金を守ることだけを目的とするシステムでもない。

TradingAIは、市場に存在する **Micro Edge（小さな優位性）**
を継続的に積み重ね、その利益を適切なリスク管理のもとで複利運用することにより、長期的な資産成長を実現することを目的とする。

短期的な利益は重要である。

しかし、その利益は常に資本保全を前提とし、一時的な大きな利益のために長期的な運用継続性を犠牲にしてはならない。

TradingAIは、

> **「守りながら増やす（Protect While Growing）」**

という思想をMoney Management全体の基本原則とする。

------------------------------------------------------------------------

## 0.2 Core Philosophy

TradingAI全体におけるMoney Managementの役割を以下のように定義する。

-   **Market Intelligence**：市場を理解する
-   **Strategy**：売買候補を生成する
-   **AI**：最終的な売買判断を行う
-   **Money Management**：資本配分とリスクを決定する
-   **Governance**：安全性を確認する
-   **Execution**：注文を執行する

Money Management の役割は、

**「勝率を上げること」ではなく、優位性のあるトレードへ最適な資金を配分し、長期的な資産成長を支えること**である。

------------------------------------------------------------------------

## 0.3 Core Values

  Value                       Priority
  --------------------------- ----------
  Capital Preservation        ★★★★★
  Risk Control                ★★★★★
  Consistent Profit           ★★★★★
  Positive Expectancy         ★★★★★
  Long-term Compound Growth   ★★★★★
  Aggressive Growth           ★★★★☆

利益とリスク管理は対立する概念ではない。

適切なリスク管理によって継続的な利益を生み出し、その利益を複利運用することで長期的な資産成長を実現する。

------------------------------------------------------------------------

## 0.4 Design Principles

### Principle 1 --- Protect Capital

資本を守ることを最優先とする。

### Principle 2 --- Exploit Micro Edge

TradingAIは、一度の大きな利益ではなく、Micro Edge
を継続的に積み重ねることを目的とする。

### Principle 3 --- Optimize Expected Value

勝率ではなく期待値を重視する。

### Principle 4 --- Compound Consistently

利益は継続して積み重ねることで価値を持つ。

### Principle 5 --- Adapt to Market Conditions

市場環境・AI
Confidence・流動性・ボラティリティ・リスク状況を総合評価し、資本配分を最適化する。

------------------------------------------------------------------------

## 0.5 Mission Statement

TradingAI Money Management
は、短期的なマイクロエッジから得られる利益を継続的に積み重ね、その利益を適切なリスク管理のもとで複利運用することで、長期的な資産成長を実現することを使命とする。

------------------------------------------------------------------------

# Table of Contents

1.  Overview
2.  Design Philosophy
3.  System Architecture
4.  Responsibilities
5.  Money Management Architecture
6.  Dashboard Integration
7.  Money Management Workspace
8.  Position Sizing Engine
9.  Capital Protection
10. Portfolio Risk Management
11. Performance Analytics
12. Simulation Engine
13. Algorithm Comparison
14. Decision Timeline
15. Configuration Management
16. API Architecture
17. Future Expansion

------------------------------------------------------------------------

# Chapter 1 --- Approved Decision Baseline

## 1.1 Scope and Initial Baseline

This is the official Money Management Decision Baseline. It specifies approved
policy only; it implements no runtime, API, UI, or deployment.

- Profile: `CAPITAL_PROTECTION_STANDARD`
- Mode: Paper
- Exchange: KuCoin Futures
- Primary Symbol: XRPUSDTM
- Initial Reference Equity: 1,000 USDT (reference only; never a fixed live value)
- Multi-Bot: Disabled / Not Permitted

## 1.2 Authority and Pipeline

Trading Decision AI makes BUY / SELL / HOLD and supplies requested size. Money
Management approves, reduces, or blocks that size; it never changes direction,
creates a decision, turns HOLD into BUY/SELL, or overrides Governance.
Governance is final safety authority. Execution submits only approved size.
AI Advisor is outside the decision pipeline and may only explain, advise, or
prepare drafts; it never automatically applies settings or trades.

    Market Data -> Detectors -> Feature Builder -> Strategy
    -> Trading Decision AI -> Money Management -> Governance -> Execution

## 1.3 States, Results, and Limits

Runtime states: `NORMAL`, `CAUTION`, `DEFENSIVE`, `LOCKED`,
`RECOVERY_25`, and `RECOVERY_50`; `RECOVERY` is presentation only.
Money Management results: `APPROVED`, `SIZE_REDUCED`, `RISK_BLOCKED`,
`INVALID_INPUT`, and `INSUFFICIENT_DATA`. `GOVERNANCE_BLOCKED` is a
broader-system result.

A hard limit sets `approvedSize = 0` and `riskAllowed = false`. A Money
Management hard block returns `RISK_BLOCKED`. Effective risk multiplier is the
minimum of all applicable ceilings. Leverage is margin-only and never raises
risk amount, raw notional, or maximum position.

## 1.4 Normative Detail and Boundary

`01_Money_Management_Specification_Additions_v1.1.md` is the normative detail
for D01--D28, formulas, enums, validation, runtime data, persistence, and
Paper/Live controls. Only Active configuration affects runtime; Draft supports
