# TR-MIGRATION-1F-5B-1: Contabo Environment File Secure Verification

**Status:** COMPLETE
**Date:** 2026-08-02 15:22 JST

## 1. Safety Check

| Check | Required | Actual | Result |
|-------|----------|--------|--------|
| hostname | vmi3480936 | vmi3480936 | PASS |
| whoami | joe4410joe | joe4410joe | PASS |
| pwd | /home/joe4410joe/tradingai_prod_v1 | /home/joe4410joe/tradingai_prod_v1 | PASS |
| branch | main | main | PASS |
| HEAD | d57de0439576c1134a67ce6055f65fc4a1c084e0 | d57de0439576c1134a67ce6055f65fc4a1c084e0 | PASS |

## 2. .env File Properties

| Property | Value | Required | Result |
|----------|-------|----------|--------|
| Exists | Yes | Yes | PASS |
| Owner | joe4410joe | joe4410joe | PASS |
| Group | joe4410joe | joe4410joe | PASS |
| Permission | 600 | 600 | PASS |
| File Size | 1083 bytes | N/A | OK |
| Modification | 2026-08-02 10:01:52 JST | N/A | OK |

## 3. Environment Variable Names

The following 16 variable names were extracted from .env:

```
BINANCE_API_KEY
BINANCE_API_SECRET
BINANCE_TESTNET
BITGET_API_KEY
BITGET_API_SECRET
BITGET_PASSPHRASE
BYBIT_API_KEY
BYBIT_API_SECRET
BYBIT_TESTNET
ENV
KUCOIN_API_KEY
KUCOIN_API_PASSPHRASE
KUCOIN_API_SECRET
REACT_APP_API_BASE
TELEGRAM_CHAT_ID
TELEGRAM_TOKEN
```

**No values, value lengths, prefixes, suffixes, hashes, tokens, passwords, API-key fragments, or private-key content are included in this report.**

## 4. Inventory Comparison

Reference file: `docs/reports/TR-MIGRATION-1F-5A_CONFIGURATION_CREDENTIAL_INVENTORY.md`

**Status: FILE NOT FOUND.** The inventory file does not exist. Comparison skipped.

## 5. Variable Classification

### SAFE_TO_PRESERVE

| Variable | Active Usage | Host-Specific | Review |
|----------|-------------|---------------|--------|
| KUCOIN_API_KEY | backend/execution/kucoin_trade.py (active) | NO | None |
| KUCOIN_API_SECRET | backend/execution/kucoin_trade.py (active) | NO | None |
| KUCOIN_API_PASSPHRASE | backend/execution/kucoin_trade.py (active) | NO | None |
| TELEGRAM_TOKEN | Bot/utils/telegram_notifier.py (active) | NO | None |
| TELEGRAM_CHAT_ID | Bot/utils/telegram_notifier.py (active) | NO | None |

### DEPRECATED_OR_UNUSED

| Variable | Reason | Host-Specific | Review |
|----------|--------|---------------|--------|
| BINANCE_API_KEY | Only in backend/core/container_old.py (dead code, never imported) | NO | Deprecation candidate |
| BINANCE_API_SECRET | Only in backend/core/container_old.py (dead code, never imported) | NO | Deprecation candidate |
| BINANCE_TESTNET | Zero references in entire codebase | NO | Deprecation candidate |
| BITGET_API_KEY | BitgetTradeClient defined but never instantiated | NO | Deprecation candidate |
| BITGET_API_SECRET | BitgetTradeClient defined but never instantiated | NO | Deprecation candidate |
| BITGET_PASSPHRASE | BitgetTradeClient defined but never instantiated | NO | Deprecation candidate |
| BYBIT_API_KEY | Zero references in entire codebase | NO | Deprecation candidate |
| BYBIT_API_SECRET | Zero references in entire codebase | NO | Deprecation candidate |
| BYBIT_TESTNET | Zero references in entire codebase | NO | Deprecation candidate |
| REACT_APP_API_BASE | Zero references (frontend uses VITE_API_BASE) | YES | Deprecation candidate |

### UNKNOWN

| Variable | Reason | Host-Specific | Review |
|----------|--------|---------------|--------|
| ENV | Zero references in codebase; may be convention-only or used by external tooling | UNKNOWN | Requires investigation |

### Summary

| Classification | Count |
|----------------|-------|
| SAFE_TO_PRESERVE | 5 |
| DEPRECATED_OR_UNUSED | 10 |
| UNKNOWN | 1 |
| HOST_VALUE_REVIEW_REQUIRED | 0 |
| EXTERNAL_ALLOWLIST_REVIEW_REQUIRED | 0 |
| NAMING_CONFLICT | 0 |

## 6. Host-Specific Analysis

| Variable | Host-Specific | Reason |
|----------|--------------|--------|
| ENV | UNKNOWN | Could contain environment label (production/staging). Never referenced in code. |
| REACT_APP_API_BASE | YES | Likely a backend API URL. Frontend migrated to VITE_API_BASE. |
| (all others) | NO | Exchange credentials and Telegram config are portable between hosts. |

## 7. Service Verification

| Service | Status | Expected | Result |
|---------|--------|----------|--------|
| nginx | inactive | inactive | PASS |
| nginx (boot) | disabled | disabled | PASS |
| redis-server | inactive | inactive | PASS |
| redis-server (boot) | disabled | disabled | PASS |

## 8. Port Verification

| Port | Listener | Expected | Result |
|------|----------|----------|--------|
| 80 | None | None | PASS |
| 443 | None | None | PASS |
| 6379 | None | None | PASS |
| 8001 | None | None | PASS |
| 5173 | None | None | PASS |

## 9. Git State Verification (Pre-Completion)

| Check | Result |
|-------|--------|
| Branch | main (unchanged) |
| HEAD | d57de0439576c1134a67ce6055f65fc4a1c084e0 (unchanged) |
| Staged files | None |
| Tracked dirty state | Unchanged (same modified/deleted set) |
| .env mode | 600 (unchanged) |
| .env content | Unmodified |

## 10. Findings

1. **INVENTORY_FILE_MISSING**: The reference inventory file `TR-MIGRATION-1F-5A_CONFIGURATION_CREDENTIAL_INVENTORY.md` does not exist. It should be created by task TR-MIGRATION-1F-5A before this task can fully compare.

2. **DEPRECATED_VARIABLES**: 10 of 16 variables are never referenced by active code. The Binance, Bybit, and Bitget API key groups, plus `REACT_APP_API_BASE`, `BINANCE_TESTNET`, and `BYBIT_TESTNET`, serve no purpose in the current codebase and retain sensitive data unnecessarily.

3. **UNTRACKED_ENV_VARIABLE**: `ENV` has no code reference but may be consumed by tooling or libraries that auto-detect it.

4. **ACTIVE_CREDENTIALS_SLIM**: Only KuCoin (3 vars) and Telegram (2 vars) are actively consumed. This is 5 of 16 variables.

5. **NO_HOST_SPECIFIC_ACTIVE**: The two potentially host-specific variables (ENV, REACT_APP_API_BASE) are both unused. No active variable is host-specific.

6. **SERVICE_AND_PORT_CLEAN**: No services running, no application ports open.

## 11. Recommendations

1. Create `TR-MIGRATION-1F-5A_CONFIGURATION_CREDENTIAL_INVENTORY.md` as prerequisite.
2. Remove DEPRECATED_OR_UNUSED variables (10 vars) to reduce secret surface area.
3. Investigate the `ENV` variable's purpose or remove it.
4. Consider migrating `REACT_APP_API_BASE` to `VITE_API_BASE` if the legacy React app build pipeline is still active.
