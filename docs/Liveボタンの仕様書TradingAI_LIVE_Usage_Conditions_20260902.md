# TradingAI LIVE 使用条件

## 目的

TradingAIのLIVE運用を、LIVE runtimeの利用と実注文権限に分離して管理する。

## 1. LIVE Runtime（DISARMED）

LIVE市場データおよびruntime処理は使用できるが、実注文は送信できない状態とする。

恒久環境条件:

- `ALLOW_LIVE=true`
- `TRADE_MODE=live`

START前条件:

- Production HEADと`origin/main`が一致し、working treeがclean
- Backend serviceがactive、listenerが1つ
- Botが`STOPPED`
- runtime stateがknownで`stateUnknown=false`
- real positionが`FLAT`
- positions、pending orders、open ordersがすべて0
- Money Management設定が有効
- GovernanceおよびEmergency Stopが`READY`
- Market Selectionのsymbol authorityが正式に確定
- LoopとAuto Tradeが`OFF`

注文権限は常に次を維持する:

- `realOrderAllowed=false`
- `executionEntryAllowed=false`
- `liveOrderEntryAllowed=false`

LIVE確認modalにはDISARMED状態、Execution/Real Order無効、Loop/Auto Trade OFFを表示する。Confirm時のみSTARTし、二重送信を禁止する。

RUNNING中も3つの注文権限がfalse、Loop/Auto TradeがOFFであることを必須とする。不一致、UNKNOWN、stale、symbol不一致、position/order検出時は直ちにEmergency Stopする。

## 2. Emergency Stop後の必須状態

- Bot `STOPPED`
- Loop `OFF`
- Auto Trade `OFF`
- execution disabled
- positions 0
- pending orders 0
- open orders 0
- `stateUnknown=false`
- real order 0
- fund movement 0

## 3. 実注文を伴うLIVE

LIVE DISARMED AcceptanceがPASSしても実注文は許可しない。実注文は別Task・別明示承認とし、MM/Governance、risk、leverage、SL/TP、market-data freshness、exchange adapter、inventory reconciliation、Emergency Stop実測を確認する。

実注文を許可する場合のみ、注文単位の正式authorityに基づいて以下を成立させる。

- `realOrderAllowed=true`
- `executionEntryAllowed=true`
- `liveOrderEntryAllowed=true`

環境変数をLIVEにするだけで注文権限をtrueにしてはならない。

## 4. 現在の恒久運用方針

- `LIVE_RUNTIME_ALWAYS_AVAILABLE=true`
- `ALLOW_LIVE=true`
- `TRADE_MODE=live`
- LIVE order entryは`DISARMED`
- 3つの注文authorityはfalse
- Loop/Auto TradeはOFF
- actual real orderは0

この条件は今後のTradingAI Operation/LIVE作業で再利用する。
