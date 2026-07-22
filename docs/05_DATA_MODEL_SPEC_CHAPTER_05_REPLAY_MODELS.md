
# 05_DATA_MODEL_SPEC

# Chapter 5 — Replay Models

## 5.1 Purpose

Replay Models は、MARKET INTELLIGENCE の判断・市場状態・Position・Timeline を
後から完全に再現するためのデータモデルを定義する。

Replay は分析・デバッグ・AI評価・検証を目的とし、
Live Trading を実行してはならない。

---

## 5.2 Replay Architecture

```
Replay Session
    ↓
Replay Cursor
    ↓
Replay Frame
    ├─ Feature Snapshot
    ├─ Decision Chain
    ├─ Timeline
    ├─ Railway
    ├─ Position
    └─ Marker
```

---

## 5.3 Replay Session

保持対象

- sessionId
- symbol
- exchange
- startTime
- endTime
- state
- playbackSpeed
- currentCursor
- createdAt

状態

```
READY
PLAYING
PAUSED
SEEKING
COMPLETED
FAILED
```

---

## 5.4 Replay Cursor

保持対象

- currentTimestamp
- eventSequence
- frameId
- progressPct

移動方法

- Play
- Pause
- Step Forward
- Step Backward
- Seek Timestamp
- Seek Position
- Seek Marker

---

## 5.5 Replay Frame

1フレームはある時刻の完全スナップショット。

含まれるもの

- Feature Snapshot
- Decision Chain
- Timeline Events
- Railway Cycle
- Active Positions
- Visible Markers

Frontend は Replay Frame を再計算しない。

---

## 5.6 Playback States

```
STOPPED
PLAYING
PAUSED
BUFFERING
SEEKING
ERROR
```

---

## 5.7 Playback Controls

対応操作

- Play
- Pause
- Resume
- Restart
- Jump Start
- Jump End
- Next Event
- Previous Event
- Speed Change

---

## 5.8 Playback Speed

標準

```
0.25x
0.5x
1x
2x
4x
8x
16x
```

高速再生でも Event の順序を変更しない。

---

## 5.9 Replay Integrity

Replay は以下を変更しない。

- Position
- Timeline
- Decision
- Marker

Replay は読み取り専用である。

---

## 5.10 Replay Validation

検証項目

- Frame 欠損
- Sequence Gap
- Timestamp Order
- Missing Decision
- Missing Feature Snapshot
- Broken Reference

---

## 5.11 Replay API Read Model

```
Replay Session
Replay Cursor
Replay Frame
Frame Entities
```

---

## 5.12 Review Checklist

- Replay は Read Only
- Live 注文しない
- Frame を再計算しない
- Event 順序を維持
- Position を変更しない
- Decision Chain を保持
- Railway を保持
- Timeline を保持
- Marker を保持

---

## Chapter 5 Status

STATUS: COMPLETE
TITLE: Replay Models
