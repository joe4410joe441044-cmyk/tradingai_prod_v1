
# 05_DATA_MODEL_SPEC

# Chapter 8 — Serialization

## 8.1 Purpose

Serialization は、Backend・Frontend・Replay・保存層の間で
Core Entity を一貫した形式で交換するためのルールを定義する。

本章は JSON を標準フォーマットとし、将来的な MessagePack や
Protocol Buffers 等への拡張も妨げない設計を前提とする。

---

## 8.2 Serialization Principles

- Backend が Authoritative
- JSON を標準とする
- UTF-8 エンコード
- UTC タイムスタンプ
- camelCase のキー名
- Enum は文字列で表現
- Null と Missing を区別する
- Frontend は受信データを再計算しない

---

## 8.3 Standard Envelope

すべての API Response は以下を基礎とする。

```json
{
  "schemaVersion":"1.0.0",
  "generatedAt":"2026-07-19T05:42:31.482Z",
  "context":{
    "mode":"LIVE",
    "readOnly":true
  },
  "data":{}
}
```

---

## 8.4 Primitive Rules

- string
- number
- boolean
- object
- array
- null

数値は IEEE-754 を前提とする。

---

## 8.5 Date & Time

- ISO-8601
- UTC
- ミリ秒精度
- タイムゾーン省略禁止

例

```
2026-07-19T05:42:31.482Z
```

---

## 8.6 Enum Rules

Enum は数値ではなく文字列。

例

```
BUY
SELL
HOLD
```

未知の Enum は UNKNOWN として扱う。

---

## 8.7 Identifier Rules

ID は文字列。

例

- pos_xxx
- evt_xxx
- fs_xxx
- rwy_xxx
- mrk_xxx

意味を持たない一意識別子とする。

---

## 8.8 Null Rules

Null は

「値は存在するが未設定」

Missing は

「フィールドが存在しない」

として扱う。

---

## 8.9 Versioning

schemaVersion を必須とする。

Major 変更では互換性を保証しない。

Minor 変更では後方互換を維持する。

---

## 8.10 Forward Compatibility

未知フィールド

- 無視可能

未知 Entity

- Unsupported Entity として保持

未知 Enum

- UNKNOWN

---

## 8.11 Validation

受信時

- schemaVersion
- entityType
- id
- timestamp
- required fields

を検証する。

---

## 8.12 Serialization Errors

例

- INVALID_SCHEMA
- UNSUPPORTED_VERSION
- INVALID_ENUM
- INVALID_TIMESTAMP
- MISSING_REQUIRED_FIELD
- INVALID_REFERENCE

---

## 8.13 API Guidelines

- gzip 圧縮対応
- Pagination 対応
- Cursor 対応
- Partial Response 可
- Immutable Entity

---

## 8.14 Review Checklist

- JSON 標準
- UTF-8
- UTC
- camelCase
- schemaVersion 必須
- Enum は文字列
- Null と Missing を区別
- Forward Compatibility 対応

---

## Chapter 8 Status

STATUS: COMPLETE
TITLE: Serialization
