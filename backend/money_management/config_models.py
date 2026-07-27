"""MM-2F formal configuration boundary for loss limits."""
from dataclasses import dataclass
from typing import Any
from .loss_models import LossLimitConfig
from .models import MoneyManagementConfig
CONFIG_SCHEMA_VERSION = "money-management-config/v1"
@dataclass(frozen=True)
class MoneyManagementConfigRoot:
    schema_version: str
    base_config: MoneyManagementConfig
    loss_limits: LossLimitConfig
    def __post_init__(self) -> None:
        if self.schema_version != CONFIG_SCHEMA_VERSION: raise ValueError("unsupported money-management config schema")
        if not isinstance(self.base_config, MoneyManagementConfig): raise TypeError("base_config must be MoneyManagementConfig")
        if not isinstance(self.loss_limits, LossLimitConfig): raise TypeError("loss_limits must be LossLimitConfig")
        pairs=(("daily_loss_warning_pct","daily_warning_pct"),("daily_loss_block_pct","daily_block_pct"),("weekly_loss_warning_pct","weekly_warning_pct"),("weekly_loss_block_pct","weekly_block_pct"),("monthly_loss_warning_pct","monthly_warning_pct"),("monthly_loss_block_pct","monthly_block_pct"),("maximum_drawdown_pct","maximum_drawdown_pct"))
        for legacy_name,nested_name in pairs:
            if getattr(self.base_config,legacy_name)!=getattr(self.loss_limits,nested_name): raise ValueError(f"loss-limit threshold mismatch: {legacy_name}")
    def to_dict(self) -> dict[str,Any]:
        return {"schema_version":self.schema_version,"base_config":self.base_config.to_dict(),"loss_limits":self.loss_limits.to_dict()}
