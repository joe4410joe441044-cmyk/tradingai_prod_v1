# TradingAI 現在の状態（引き継ぎ用）

## 🎯 現在のフェーズ

* 残高取得：OK（KuCoin）
* Redis：導入済み
* UI：あり
* 次：ポジションサイズを実際に計算して反映

---

## 🧱 コア構成

### Redis（状態管理）

* redis_client.py
* redis_pubsub.py（未使用・将来使用）

### ロジック

* risk_manager.py ← NEW（これが重要）

### 設定

* config.py（フォールバック用）

---

## 🎯 ロット計算ロジック

size = (balance * risk_percent) / price

* risk_percent：Redis優先
* fallback：config.py

---

## 🧱 現在の実装ルール

* Exchange層：API接続のみ
* Redis：状態保存
* risk_manager：サイズ計算
* ExecutionEngine：実行

---

## 🚫 やってはいけない

* PubSubに今ハマる
* UIを先に作り込む
* 固定ロットに戻る

---

## ▶ 次にやること（最優先）

1. risk_manager.py 作成
2. ExecutionEngineに組み込み
3. sizeログ確認

---

## ▶ 次フェーズ

* UI → risk変更
* PubSub導入
* 実注文

---

## 🧠 設計思想（重要）

これはBOTではなく

👉「資金管理エンジン」

---

## 🎯 次チャットで言うこと

「risk_managerからやる」
