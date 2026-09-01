# TradingAI PAPER-to-LIVE Development & Validation Workflow Specification

**Document Type:** Development / Git / Validation Operational
Specification\
**Status:** ACTIVE\
**Version:** 1.0\
**Effective From:** 2026-09-01

------------------------------------------------------------------------

# 1. Purpose

本仕様書は、TradingAIにおける今後の開発・修正・PAPER検証・LIVE移行を、

-   Production dirtyを発生させない
-   Worktreeを開発・修正の正式作業場所とする
-   PAPER検証時点で可能な限りLIVE品質まで検証する
-   PAPER専用実装とLIVE実装の乖離を防ぐ
-   Production Controlを常時cleanに維持する
-   LIVE移行時の追加修正を最小化する
-   実注文権限をPAPER検証から完全に分離する

ことを目的として定義する。

基本思想は以下とする。

> PAPERは単なる模擬取引環境ではない。
>
> PAPERを「LIVE直前のProduction Acceptance Environment」として扱う。
>
> PAPERでLIVEと共有可能なデータ経路、判断経路、Risk Authority、Execution
> Contract、Lifecycle、Recovery、Diagnosticsまで検証し、LIVE固有の実注文権限・取引所認証・実約定だけを最後のLIVE
> Gateとして残す。

------------------------------------------------------------------------

# 2. Fundamental Rule

コード開発・修正は原則Worktreeで行う。

Production Control `/home/joe4410joe/tradingai_prod_v1` は canonical
main / Production runtime / final PAPER acceptance / final LIVE
acceptance のために使用し、原則直接コード編集を行わない。

通常時は `git status = clean` を維持する。

------------------------------------------------------------------------

# 3. Repository Architecture

``` text
/home/joe4410joe/tradingai_prod_v1
├── main
├── Production Runtime
├── PAPER Final Acceptance
└── LIVE Final Acceptance
    └── 原則直接編集禁止

/home/joe4410joe/tradingai_prod_v1.worktrees/
├── market-intelligence
├── money-management
├── operation-*
├── microstructure-*
├── execution-*
├── paper-*
├── fix-*
└── integration-*
```

------------------------------------------------------------------------

# 4. Production Control Rule

Production Controlでは source直接編集、temporary fix、debug/test
code追加、backup/diagnostic script生成、experimental
configuration変更、untracked source生成、Production-only
patch/commitを原則禁止する。

Productionで問題を発見した場合もその場で修正せず、必ずWorktreeへ戻す。

------------------------------------------------------------------------

# 5. Standard Development Flow

``` text
Production PAPER
→ Problem Detection
→ Dedicated Worktree
→ Root Cause Analysis
→ Implementation
→ Unit / Regression Tests
→ PAPER Simulation / Isolated Validation
→ Commit
→ Clean Integration Worktree
→ Cross-Module Regression
→ main Integration
→ Production Sync
→ Controlled Runtime Restart
→ Production PAPER Acceptance
→ LIVE Readiness Acceptance
```

------------------------------------------------------------------------

# 6. Worktree Rule

Worktreeは開発途中でdirtyになってもよい。ただし、そのdirty
stateをProduction Controlへ直接コピーしてはならない。

Productionへ移動可能なのは原則として
`reviewed + tested + committed code` のみとする。

------------------------------------------------------------------------

# 7. Integration Worktree

複数モジュールを統合する場合、Production
Controlをintegration場所として使用しない。

専用integration worktree（例:
`/home/joe4410joe/tradingai_prod_v1.worktrees/integration-YYYYMMDD`）で
merge / cherry-pick / semantic conflict resolution / regression tests /
frontend build / backend tests / authority verification を実施する。

Integration worktreeがcleanかつPASSしてからmainへ反映する。

------------------------------------------------------------------------

# 8. PAPER Validation Philosophy

PAPERはLIVEとは別製品として扱わない。可能な限り以下を共通化する。

``` text
Market Data
↓
Market Selection
↓
Market Intelligence
↓
DOM / Recent Trades
↓
Microstructure Edge
↓
AI / Decision
↓
Entry Decision
↓
Risk / MM Authority
↓
Execution Decision
↓
Execution Contract
↓
PAPER or LIVE Adapter
```

PAPER/LIVE差分は可能な限りExecution境界より後ろに限定する。

------------------------------------------------------------------------

# 9. PAPER-to-LIVE Shared Path

PAPERでLIVE品質として検証する対象:

-   Market Data: WebSocket lifecycle / reconnect / freshness / stale
    detection / symbol isolation / timestamp integrity / market
    readiness / feed failure handling
-   Market Intelligence: active symbol / DOM / Recent Trades / market
    context / marker generation / stale context rejection / data-quality
    handling
-   Microstructure Edge: entry / exit / early exit / confirmation state
    / reset-re-entry / symbol transition / invalid-state rejection
-   AI / Decision: decision input/output / HOLD / BUY / SELL / BLOCK /
    unavailable / stale / authority boundaries
-   Money Management: available capital / risk budget / exposure /
    position sizing / drawdown authority / risk state /
    executionEntryAllowed / fail-closed / unavailable handling
-   Execution: execution intent / side / symbol / quantity / leverage /
    order parameters / entry-exit relationship / duplicate prevention /
    stale rejection / execution authority

------------------------------------------------------------------------

# 10. PAPER / LIVE Boundary

PAPERは実注文を取引所へ送信せずPAPER execution
adapterを使用する。LIVEはLIVE execution
adapterを使用し実取引所APIへ注文を送信する。

PAPER acceptanceで検証できないLIVE固有項目は主として、LIVE API
authentication、exchange LIVE order acceptance、actual exchange order
ID/fills、real slippage/fee、partial fills、exchange-specific
rejection、cancel/replace、actual balance mutation、network/API
latency、LIVE recoveryとする。

------------------------------------------------------------------------

# 11. Critical Safety Rule

PAPERからLIVEへ移行するためにPAPER safety
guardを削除・迂回・無効化してはならない。

禁止例: realOrderAllowed強制true、MM fail-closed bypass、stateUnknown
bypass、stale market bypass、PAPER bootstrap
bypass、executionEntryAllowed bypass、LIVE confirmation bypass、risk
authority bypass。

PAPERでBLOCKされた場合、「テストのために通す」ことは禁止し、BLOCK原因を修正してから再検証する。

------------------------------------------------------------------------

# 12. PAPER Acceptance Levels

## LEVEL 1 --- Runtime Acceptance

canonical runtime / Git clean / service healthy / PAPER / STOPPED
initial state / no real-order authority / market connectivity /
lifecycle integrity。

## LEVEL 2 --- Trading Pipeline Acceptance

``` text
Market Data
→ Market Intelligence
→ Microstructure
→ Decision
→ MM
→ Execution Intent
→ PAPER Execution
→ Position
→ Exit
→ FLAT
```

## LEVEL 3 --- LIVE Readiness Acceptance

PAPER cycle完了後、同じcycleがLIVE
adapterへ切り替わった場合に必要となる条件を検査する。ただし実注文は送らない。

------------------------------------------------------------------------

# 13. LIVE Readiness Acceptance

PAPER acceptance完了時に必ずLIVE readinessも同時評価する。

LIVE execution path、PAPER/LIVE contract compatibility、LIVE authority
fail-closed、explicit confirmation、realOrderAllowed false by
default、safe mode switching、state isolation、position/order
authority、MM authority、fresh market data、symbol
authority、recovery、emergency stopを確認する。

これを `LIVE_READY_WITHOUT_EXECUTION` として評価する。

------------------------------------------------------------------------

# 14. LIVE_READY_WITHOUT_EXECUTION

これは「LIVE注文を送信した」という意味ではない。

> PAPERで検証可能なLIVE共通経路がすべて合格し、LIVE固有の実取引所execution
> validationだけが残っている状態。

------------------------------------------------------------------------

# 15. LIVE Gate

``` text
PRODUCTION_GIT_CLEAN = YES
LOCAL_MAIN_CANONICAL = YES
ORIGIN_MAIN_CANONICAL = YES
RUNTIME_CANONICAL = YES
BACKEND_HEALTHY = YES
PAPER_ACCEPTANCE = PASS
MARKET_DATA = PASS
MARKET_INTELLIGENCE = PASS
MICROSTRUCTURE = PASS
AI_DECISION = PASS
MM_AUTHORITY = PASS
EXECUTION_CONTRACT = PASS
RECOVERY = PASS
EMERGENCY_STOP = PASS
STATE_UNKNOWN = FALSE
MARKET_STALE = FALSE
REAL_ORDER_ALLOWED_DEFAULT = FALSE
LIVE_READY_WITHOUT_EXECUTION = YES
```

一つでも満たさない場合、LIVE executionへ進まない。

------------------------------------------------------------------------

# 16. MM Rule Before LIVE

Money ManagementはPAPER開発途中では一時的に UNKNOWN / UNAVAILABLE /
fail-closed でもよい。ただしLIVE移行前には必ずE2E接続を証明する。

``` text
Trading Runtime
↓
MM Runtime
↓
Capital
↓
Risk
↓
Exposure
↓
Position Size
↓
Execution Authority
```

これが成立しない状態ではLIVE禁止。MMを迂回してLIVEへ進んではならない。

------------------------------------------------------------------------

# 17. PAPER Failure Handling

``` text
PAPER FAILURE
↓
STOP BOT
↓
FLAT / ORDERS 0確認
↓
Dedicated Worktree
↓
Fix
↓
Tests
↓
Commit
↓
Integration
↓
main
↓
Production
↓
Controlled Restart
↓
PAPER RETEST
```

Production PAPERで問題が見つかってもProductionで修正しない。

------------------------------------------------------------------------

# 18. Production Dirty-Zero Rule

Production Controlは原則として常時 `git status --short`
EMPTYを要求する。

dirty発生時は generated artifact / runtime artifact / ignored
environment / accidental edit / diagnostic file / valuable source change
/ unknown provenance 等へ分類する。

valuable/unknown sourceを削除する前に必ずpreservationする。

------------------------------------------------------------------------

# 19. Build Rule

Frontend buildは可能な限りWorktreeまたはclean integration
environmentで行う。

Production buildが必要な場合もcanonical build inputと完全一致させる。

`.env*`、`VITE_*`、Node/npm version、dependency lock、Vite
configurationを環境依存build inputとして扱い、Production-only build
environmentを作らない。

------------------------------------------------------------------------

# 20. Environment Rule

Git ignoredだからといってbuild/runtime authority外とはみなさない。特に
`.env*` は正式なbuild inputとして扱う。

Production固有envが必要な場合は、その存在理由・authority・PAPER/LIVE差分を明文化する。

------------------------------------------------------------------------

# 21. Runtime Restart Rule

main更新後、必要なBackend変更が存在する場合はcontrolled restartを行う。

restart前: Git clean / canonical HEAD / PAPER / bot STOPPED / LOOP OFF /
AUTO OFF / LIVE inactive / FLAT / orders 0 / realOrderAllowed false。

restart後: new PID / correct WorkingDirectory / backend health / Git
clean / safe stopped state。

------------------------------------------------------------------------

# 22. Production Testing Rule

Productionで許可される検証はcanonical codeに対するAcceptance
Testとする。Productionを開発sandboxとして使用しない。

------------------------------------------------------------------------

# 23. PAPER Execution Safety

PAPER execution時は必ず:

``` text
mode = PAPER
realOrderAllowed = false
```

PAPER cycle中にLIVE order pathが呼ばれた場合は重大FAIL
`FAIL_LIVE_AUTHORITY_LEAK` とし即時停止する。

------------------------------------------------------------------------

# 24. LIVE Dry Validation

実LIVE注文前に、LIVE modeへ切り替えなくても検証可能なLIVE
contractを可能な限り検査する。

order schema / quantity precision / symbol mapping / leverage
constraints / minimum quantity/notional / position side / reduce-only /
cancel semantics / authentication configuration presence / authority
gates / confirmation requirements。

実注文は送らない。

------------------------------------------------------------------------

# 25. First LIVE Validation

PAPER acceptanceとLIVE readinessが完全PASSした後のみ実施する。

PAPER検証の延長で自動的にLIVE注文を開始してはならず、必ず明示的なLIVE
authorizationを要求する。

------------------------------------------------------------------------

# 26. No Automatic PAPER-to-LIVE Escalation

禁止:

``` text
PAPER PASS
↓
automatic LIVE START
```

必須:

``` text
PAPER PASS
↓
LIVE_READY_WITHOUT_EXECUTION
↓
STOP
↓
Human Review
↓
Explicit LIVE Authorization
↓
LIVE Validation
```

------------------------------------------------------------------------

# 27. Preservation Rule

重要な旧Production差分・diagnostic evidence・historical
snapshotは、新canonical runtimeのPAPER
acceptanceが完了するまで削除しない。必要に応じてLIVE
acceptance完了まで保持する。

preservation branchをProduction runtime sourceとして使用しない。

------------------------------------------------------------------------

# 28. Final Acceptance Report

``` text
PRODUCTION_GIT_CLEAN:
RUNTIME_CANONICAL:
BACKEND_HEALTHY:
PAPER_MODE:
REAL_ORDER_ALLOWED:
MARKET_DATA:
MARKET_READINESS:
MARKET_INTELLIGENCE:
DOM:
RECENT_TRADES:
MICROSTRUCTURE:
AI_DECISION:
MM_AUTHORITY:
EXECUTION_INTENT:
PAPER_EXECUTION:
ENTRY:
POSITION:
EXIT:
RETURN_TO_FLAT:
OPEN_ORDERS_AFTER_TEST:
LIVE_AUTHORITY_LEAK:
RECOVERY:
EMERGENCY_STOP:
PAPER_ACCEPTANCE:
LIVE_READY_WITHOUT_EXECUTION:
```

------------------------------------------------------------------------

# 29. Development Completion Definition

「PAPER完成」は単にPAPER注文が通った状態を意味しない。

``` text
PAPER pipeline E2E PASS
+
LIVE shared path PASS
+
LIVE authority PASS
+
MM authority PASS
+
Execution contract PASS
+
Recovery PASS
+
Emergency PASS
+
Production clean
+
Runtime canonical
```

この状態を `PAPER_ACCEPTED_LIVE_READY_WITHOUT_EXECUTION` と定義する。

------------------------------------------------------------------------

# 30. Final Operating Principle

> Develop in Worktrees.
>
> Integrate in Clean Worktrees.
>
> Keep Production Clean.
>
> Validate PAPER in Production.
>
> Validate LIVE-shared behavior during PAPER.
>
> Never bypass authority to make a test pass.
>
> Promote only committed and validated code.
>
> Require explicit authorization before real LIVE execution.

日本語定義:

> 開発・修正はWorktree。
>
> 統合もcleanなWorktree。
>
> Production Controlは常時clean。
>
> PAPER最終E2EだけProduction。
>
> PAPER時点でLIVE共通経路まで検証する。
>
> BLOCKを迂回してテストを通さない。
>
> Productionへ入れるのは検証済みcommitのみ。
>
> 実LIVE注文は必ず独立した明示承認を要求する。

------------------------------------------------------------------------

# 31. Current Adoption

本仕様はProduction dirty-zero達成後から適用する。

以後、新規開発・PAPER修正・LIVE準備について、Production
Controlへの直接開発を原則禁止し、本Worktree/PAPER-to-LIVE方式をTradingAI標準運用とする。
