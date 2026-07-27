"""Pure MM-2F configuration resolution."""
from .config_models import MoneyManagementConfigRoot
from .loss_models import LossLimitConfig

def resolve_loss_limit_config(root_config: MoneyManagementConfigRoot) -> LossLimitConfig:
    if not isinstance(root_config, MoneyManagementConfigRoot):
        raise TypeError("root_config must be MoneyManagementConfigRoot")
    return root_config.loss_limits
