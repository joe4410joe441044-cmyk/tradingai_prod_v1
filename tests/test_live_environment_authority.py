import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _fresh_config(*, allow_live=None, trade_mode=None):
    environment = os.environ.copy()
    environment.pop("ALLOW_LIVE", None)
    environment.pop("TRADE_MODE", None)
    if allow_live is not None:
        environment["ALLOW_LIVE"] = allow_live
    if trade_mode is not None:
        environment["TRADE_MODE"] = trade_mode
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; import backend.config as config; "
                "print(json.dumps([config.ALLOW_LIVE, config.TRADE_MODE]))"
            ),
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


@pytest.mark.parametrize(
    ("allow_live", "trade_mode", "expected"),
    [
        (None, None, [False, "paper"]),
        ("false", "paper", [False, "paper"]),
        ("true", "live", [True, "live"]),
        ("invalid", "live", [False, "live"]),
        ("true", "invalid", [True, "paper"]),
    ],
)
def test_fresh_process_environment_authority(
    allow_live, trade_mode, expected
):
    assert _fresh_config(
        allow_live=allow_live,
        trade_mode=trade_mode,
    ) == expected
