"""Strict default-OFF feature flag for the isolated PROP demo."""

from __future__ import annotations

import os
from typing import Mapping

PROP_ISOLATED_DEMO_FLAG = "PROP_ISOLATED_DEMO_ENABLED"


def prop_isolated_demo_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Enable only for the exact, documented lowercase value ``true``."""

    source = os.environ if environ is None else environ
    return source.get(PROP_ISOLATED_DEMO_FLAG) == "true"
