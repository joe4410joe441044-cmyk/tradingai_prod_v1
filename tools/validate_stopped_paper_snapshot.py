#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.bot_manager.bot_manager import BotManager


class ValidatorArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        print(json.dumps({
            "valid": False,
            "reason": "CLI_ARGUMENT_ERROR",
        }, separators=(",", ":")), file=sys.stderr)
        raise SystemExit(4)


def build_parser():
    parser = ValidatorArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--expected-runtime-instance-id", required=True)
    parser.add_argument("--expected-generation", required=True, type=int)
    return parser


def validate(args):
    expected_runtime_instance_id = args.expected_runtime_instance_id
    if (
        not isinstance(expected_runtime_instance_id, str)
        or not expected_runtime_instance_id.strip()
    ):
        return 4, {
            "valid": False,
            "reason": "CLI_ARGUMENT_ERROR",
        }
    expected_runtime_instance_id = expected_runtime_instance_id.strip()

    manager = BotManager()
    inspection = manager.inspect_stopped_paper_durable_snapshot(args.path)
    reason = inspection.get("reason")

    if inspection.get("valid") is not True:
        exit_code = 2 if reason in {
            "DURABLE_SNAPSHOT_MISSING",
            "DURABLE_SNAPSHOT_SYMLINK_NOT_ALLOWED",
            "DURABLE_SNAPSHOT_NOT_REGULAR_FILE",
            "DURABLE_SNAPSHOT_FILE_IDENTITY_CHANGED",
            "DURABLE_SNAPSHOT_CORRUPT",
            "DURABLE_SNAPSHOT_READ_FAILED",
        } else 1
        return exit_code, {
            "valid": False,
            "reason": reason or "STATE_UNKNOWN",
        }

    if (
        inspection.get("evidenceRuntimeInstanceId")
        != expected_runtime_instance_id
    ):
        return 3, {
            "valid": False,
            "reason": "EXPECTED_RUNTIME_INSTANCE_MISMATCH",
        }

    if inspection.get("generation") != args.expected_generation:
        return 3, {
            "valid": False,
            "reason": "EXPECTED_GENERATION_MISMATCH",
        }

    return 0, {
        "valid": True,
        "reason": None,
        "runtimeInstanceId": inspection.get(
            "evidenceRuntimeInstanceId"
        ),
        "generation": inspection.get("generation"),
        "capturedAt": inspection.get("capturedAt"),
    }


def main(argv=None):
    args = build_parser().parse_args(argv)
    exit_code, result = validate(args)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
