"""Server-only, Trading-OFF Hyro Trial refresh boundary.

The browser receives only a fixed safe projection. Credentials and Hyro
identifiers are resolved inside the server process and never enter responses.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import os
from threading import Lock
from typing import Any, Callable, Mapping, Protocol

from backend.execution.hyro_mcp_http_transport import (
    HYRO_OFFICIAL_MCP_ENDPOINT,
    HyroMcpHttpConfig,
    HyroMcpHttpError,
    HyroMcpHttpTransport,
)

TOKEN_ENV = "HYRO_MCP_TRADING_OFF_TOKEN"
TRIAL_ID_ENV = "HYRO_MCP_TRIAL_PUBLIC_ID"
ENABLED_ENV = "HYRO_MCP_READ_REFRESH_ENABLED"
TOOLS = ("get_challenge", "get_stage_metrics", "get_stage_trades")
MAX_TRADE_PAGES = 5


class HyroTrialReadError(RuntimeError):
    def __init__(self, safe_code: str, status_code: int = 503) -> None:
        self.safe_code = safe_code
        self.status_code = status_code
        super().__init__(safe_code)


class ToolTransport(Protocol):
    def initialize_and_list_tools(self): ...
    def call_tool_object(self, name: str, arguments: Mapping[str, Any]): ...


@dataclass(frozen=True, repr=False)
class HyroTrialReadConfig:
    enabled: bool
    token_reference: str | None = field(default=None, repr=False)
    trial_public_id: str | None = field(default=None, repr=False)

    @classmethod
    def from_environment(
        cls,
        reader: Callable[[str], str | None] = os.environ.get,
    ) -> "HyroTrialReadConfig":
        return cls(
            enabled=reader(ENABLED_ENV) == "true",
            token_reference=TOKEN_ENV if reader(TOKEN_ENV) else None,
            trial_public_id=reader(TRIAL_ID_ENV),
        )

    @property
    def ready(self) -> bool:
        return (
            self.enabled
            and self.token_reference == TOKEN_ENV
            and isinstance(self.trial_public_id, str)
            and bool(self.trial_public_id.strip())
            and self.trial_public_id == self.trial_public_id.strip()
        )


@dataclass(frozen=True, repr=False)
class EnvironmentHyroCredentialResolver:
    reader: Callable[[str], str | None] = field(default=os.environ.get, repr=False)

    def resolve(self, reference: str) -> str:
        if reference != TOKEN_ENV:
            raise RuntimeError("credential unavailable")
        value = self.reader(reference)
        if not isinstance(value, str) or not value:
            raise RuntimeError("credential unavailable")
        return value


def _decimal(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return float(number) if number.is_finite() else None


def _nested_number(payload: Mapping[str, Any], *paths: tuple[str, ...]) -> float | None:
    for path in paths:
        current: object = payload
        for name in path:
            if not isinstance(current, Mapping) or name not in current:
                break
            current = current[name]
        else:
            parsed = _decimal(current)
            if parsed is not None:
                return parsed
    return None


def _tool_contract_ok(tool: object, required: list[str]) -> bool:
    description = getattr(tool, "description", None)
    schema = getattr(tool, "input_schema", None)
    if not isinstance(description, str):
        return False
    lowered = description.lower()
    if "trade scope" in lowered or "requires trade" in lowered:
        return False
    return (
        isinstance(schema, Mapping)
        and schema.get("type") == "object"
        and schema.get("required") == required
    )


def _trade_page(payload: Mapping[str, Any]) -> dict[str, Any]:
    rows = payload.get("data")
    paging = tuple(payload.get(name) for name in ("page", "pageSize", "total", "totalPages"))
    paging_valid = all(type(value) is int and value >= 0 for value in paging)
    daily: dict[str, Decimal] = defaultdict(Decimal)
    accepted_days: set[str] = set()
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            timestamp = row.get("closedAt")
            net_pnl = _decimal(row.get("netPnl"))
            if not isinstance(timestamp, str) or net_pnl is None:
                continue
            try:
                moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                continue
            day = moment.date().isoformat()
            daily[day] += Decimal(str(net_pnl))
            if row.get("accepted") is True:
                accepted_days.add(day)
    return {
        "page": payload.get("page") if paging_valid else None,
        "totalPages": payload.get("totalPages") if paging_valid else None,
        "daily": daily,
        "acceptedDays": accepted_days,
    }


class HyroTrialReadService:
    def __init__(
        self,
        *,
        config: HyroTrialReadConfig | None = None,
        credential_resolver: object | None = None,
        transport_factory: Callable[[HyroTrialReadConfig], ToolTransport] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._config = config or HyroTrialReadConfig.from_environment()
        self._resolver = credential_resolver or EnvironmentHyroCredentialResolver()
        self._transport_factory = transport_factory or self._official_transport
        self._clock = clock
        self._lock = Lock()

    def _official_transport(self, config: HyroTrialReadConfig) -> HyroMcpHttpTransport:
        return HyroMcpHttpTransport(
            HyroMcpHttpConfig(
                credential_reference=config.token_reference,
                endpoint=HYRO_OFFICIAL_MCP_ENDPOINT,
                allow_network=True,
            ),
            self._resolver,
            allowed_tool_names=TOOLS,
        )

    def refresh(self) -> dict[str, Any]:
        if not self._config.enabled:
            raise HyroTrialReadError("HYRO_TRIAL_REFRESH_DISABLED", 404)
        if not self._config.ready:
            raise HyroTrialReadError("HYRO_TRIAL_REFRESH_CONFIGURATION_INCOMPLETE")
        if not self._lock.acquire(blocking=False):
            raise HyroTrialReadError("HYRO_TRIAL_REFRESH_IN_PROGRESS", 409)
        try:
            return self._refresh_locked()
        except HyroTrialReadError:
            raise
        except (HyroMcpHttpError, PermissionError):
            raise HyroTrialReadError("HYRO_TRIAL_READ_FAILED") from None
        except Exception:
            raise HyroTrialReadError("HYRO_TRIAL_READ_FAILED") from None
        finally:
            self._lock.release()

    def _refresh_locked(self) -> dict[str, Any]:
        challenge_id = self._config.trial_public_id
        if not isinstance(challenge_id, str):
            raise HyroTrialReadError("HYRO_TRIAL_REFRESH_CONFIGURATION_INCOMPLETE")
        transport = self._transport_factory(self._config)
        discovery = transport.initialize_and_list_tools()
        inventory = {tool.name: tool for tool in discovery.tools}
        contracts = {
            "get_challenge": ["challengePublicId"],
            "get_stage_metrics": ["stagePublicId"],
            "get_stage_trades": ["stagePublicId"],
        }
        if any(not _tool_contract_ok(inventory.get(name), required) for name, required in contracts.items()):
            raise HyroTrialReadError("HYRO_TRIAL_READ_CONTRACT_MISMATCH")

        challenge, _ = transport.call_tool_object(
            "get_challenge", {"challengePublicId": challenge_id},
        )
        if challenge.get("publicId") != challenge_id:
            raise HyroTrialReadError("HYRO_TRIAL_CHALLENGE_ID_MISMATCH", 409)
        stage = challenge.get("currentStage")
        stage_id = stage.get("publicId") if isinstance(stage, Mapping) else None
        if not isinstance(stage_id, str) or not stage_id:
            raise HyroTrialReadError("HYRO_TRIAL_STAGE_ID_UNCONFIRMED")

        metrics, _ = transport.call_tool_object(
            "get_stage_metrics", {"stagePublicId": stage_id, "period": "all"},
        )
        daily: dict[str, Decimal] = defaultdict(Decimal)
        accepted_days: set[str] = set()
        pages_read = 0
        trades_complete = False
        try:
            for page_number in range(1, MAX_TRADE_PAGES + 1):
                payload, _ = transport.call_tool_object(
                    "get_stage_trades",
                    {"stagePublicId": stage_id, "period": "all", "page": page_number, "pageSize": 100},
                )
                parsed = _trade_page(payload)
                pages_read += 1
                for day, amount in parsed["daily"].items():
                    daily[day] += amount
                accepted_days.update(parsed["acceptedDays"])
                total_pages = parsed["totalPages"]
                if parsed["page"] != page_number or total_pages is None:
                    break
                if page_number >= total_pages:
                    trades_complete = total_pages <= MAX_TRADE_PAGES
                    break
        except (HyroMcpHttpError, PermissionError):
            trades_complete = False

        observed_at = self._clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        status = challenge.get("status")
        stage_type = stage.get("type") if isinstance(stage, Mapping) else None
        rule_sheet = challenge.get("ruleSheet")
        return {
            "id": "hyro-issued-trial-redacted",
            "accountName": "Hyro Terminal 無料Trial — 25,000 USDT",
            "plan": "FREE TRIAL（購入予定のHyro Coreとは別口座）",
            "stage": stage_type.upper() if isinstance(stage_type, str) else "UNKNOWN",
            "period": "swing",
            "platform": "HYRO TERMINAL",
            "updatedAt": observed_at,
            "source": "HYRO OFFICIAL MCP / SERVER READ-ONLY REFRESH",
            "readKind": "ISSUED_READ_ONLY",
            "sample": False,
            "readOnly": True,
            "status": status.upper() if isinstance(status, str) else "UNKNOWN",
            "dataQuality": "READY" if trades_complete else "PARTIAL",
            "stagePublicIdVerified": True,
            "rules": {
                "ruleSheetPresent": isinstance(rule_sheet, list),
                "ruleSheetEntryCount": len(rule_sheet) if isinstance(rule_sheet, list) else None,
                "adoptedRuleValueCount": 0,
                "minimumTradingDays": None,
                "minimumTradingDaysUnit": None,
                "note": "Trial rule values are not adopted without a confirmed type/unit contract",
            },
            "metrics": {
                "source": "GET_STAGE_METRICS_AND_GET_STAGE_TRADES",
                "observedAt": observed_at,
                "initialBalance": _nested_number(metrics, ("initialBalance",), ("equityMetrics", "initialBalance")),
                "currentEquity": _nested_number(metrics, ("equity",), ("currentEquity",), ("equityMetrics", "equity"), ("equityMetrics", "currentEquity")),
                "currentDrawdown": _nested_number(metrics, ("equityMetrics", "currentDrawdown")),
                "currentLoss": _nested_number(metrics, ("equityMetrics", "currentLoss")),
                "utcDayStartEquity": None,
                "intradayMinimumEquity": None,
                "qualifyingTradingDays": len(accepted_days) if trades_complete else None,
                "dailyNetResults": [float(daily[day]) for day in sorted(daily)] if trades_complete else None,
                "tradeHistoryComplete": trades_complete,
                "tradePagesRead": pages_read,
                "tradeMaximumPages": MAX_TRADE_PAGES,
                "periodLabel": "all / as observed; explicit start/end not supplied",
                "pnl": None,
                "positions": None,
                "openOrders": None,
                "conditionalOrders": None,
            },
        }
