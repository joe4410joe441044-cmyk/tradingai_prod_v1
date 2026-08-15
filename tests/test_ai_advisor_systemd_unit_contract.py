import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIT_NAME = "tradingai-ai-advisor-live-validation.service"
UNIT = ROOT / ("deploy/systemd/" "tradingai-ai-advisor-live-validation.service")
RUNBOOK = ROOT / "docs/ai_advisor/systemd-credential-smoke-runbook.md"
MATRIX = ROOT / "docs/ai_advisor/PRODUCTION_CONFIGURATION_MATRIX_CANDIDATE.md"
READINESS = ROOT / "docs/ai_advisor/FINAL_OFFLINE_PRODUCTION_READINESS_PACKAGE.md"
PRODUCTION_RUNBOOK = ROOT / "docs/ai_advisor/AI_ADV_1F_BATCH2_PRODUCTION_RUNBOOK.md"
SOURCE_DIRECTORY = "/etc/credstore.encrypted/tradingai-ai-advisor-live-validation"
CREDENTIALS = ("AI_ADVISOR_AUTH_TOKEN", "OPENAI_API_KEY")


class SystemdUnitContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.unit = UNIT.read_text(encoding="utf-8")
        cls.runbook = RUNBOOK.read_text(encoding="utf-8")
        cls.documents = tuple(
            path.read_text(encoding="utf-8")
            for path in (MATRIX, READINESS, PRODUCTION_RUNBOOK)
        )

    def test_unit_is_transient_oneshot_without_activation_or_production_link(self):
        self.assertIn("Type=oneshot", self.unit)
        self.assertIn("Restart=no", self.unit)
        self.assertIn("RemainAfterExit=no", self.unit)
        self.assertIn("SuccessExitStatus=0", self.unit)
        self.assertNotIn("[Install]", self.unit)
        self.assertNotIn("WantedBy=", self.unit)
        self.assertNotIn("Requires=tradingbot.service", self.unit)
        self.assertNotIn("Wants=tradingbot.service", self.unit)
        self.assertNotIn("After=tradingbot.service", self.unit)
        for forbidden in ("OnCalendar=", "ListenStream=", "ListenDatagram="):
            self.assertNotIn(forbidden, self.unit)

    def test_credential_names_paths_and_encryption_are_single_contract(self):
        for credential in CREDENTIALS:
            directive = (
                f"LoadCredentialEncrypted={credential}:"
                f"{SOURCE_DIRECTORY}/{credential}"
            )
            self.assertEqual(self.unit.count(directive), 1)
            self.assertIn(f"`{SOURCE_DIRECTORY}/{credential}`", self.runbook)
        self.assertNotIn("LoadCredential=", self.unit)
        self.assertNotIn("Environment=AI_ADVISOR", self.unit)
        self.assertIn("`root:root` mode `0700`", self.runbook)
        self.assertIn("`root:root` mode `0600`", self.runbook)

    def test_entrypoint_approval_and_runtime_policy_are_fixed(self):
        entrypoint = (
            "ExecStart=/home/joe4410joe/tradingai_prod_v1/venv/bin/python "
            "-m backend.ai_advisor.isolated_smoke_runner --mode LIVE_ONE_SHOT "
            "--live-one-shot-approval "
            "'AI-ADV-1E9 LIVE TEST APPROVED: ONE REQUEST'"
        )
        self.assertIn(entrypoint, self.unit)
        self.assertIn("systemd-run --wait --collect", self.runbook)
        self.assertNotIn("systemd-run --pty", self.runbook)
        self.assertNotIn("Python `getpass`", self.runbook)
        self.assertIn("--live-one-shot-approval", self.runbook)
        self.assertEqual(
            self.unit.count("'AI-ADV-1E9 LIVE TEST APPROVED: ONE REQUEST'"),
            1,
        )
        self.assertIn("StandardInput=null", self.unit)
        self.assertIn("retry zero", self.runbook)
        self.assertIn(
            "at most one provider call",
            " ".join(self.runbook.split()),
        )
        self.assertIn("redirect locations", self.runbook)
        self.assertIn("StandardOutput=journal", self.unit)
        self.assertIn("StandardError=journal", self.unit)
        self.assertIn("--property=ProtectSystem=strict", self.runbook)
        self.assertIn("--property=SuccessExitStatus=0", self.runbook)
        self.assertIn("PrivateNetwork=yes", self.runbook)
        self.assertIn("CREDENTIAL_PROBE_AVAILABLE", self.runbook)
        self.assertIn("SystemdCredentialLoader", self.runbook)
        self.assertIn(
            "Environment=TRADINGAI_ISOLATED_STDIO_ONLY=true",
            self.unit,
        )
        self.assertIn(
            "--property=Environment=TRADINGAI_ISOLATED_STDIO_ONLY=true",
            self.runbook,
        )

    def test_sandbox_timeout_and_read_only_filesystem_are_explicit(self):
        required = (
            "User=joe4410joe",
            "Group=joe4410joe",
            "TimeoutStartSec=120",
            "NoNewPrivileges=yes",
            "PrivateTmp=yes",
            "PrivateDevices=yes",
            "ProtectSystem=strict",
            "ProtectHome=tmpfs",
            "BindReadOnlyPaths=/home/joe4410joe/tradingai_prod_v1",
            "CapabilityBoundingSet=",
            "AmbientCapabilities=",
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        )
        for directive in required:
            self.assertIn(directive, self.unit)

    def test_lifecycle_names_exact_rollback_rotation_and_deletion_targets(self):
        for heading in (
            "### Placement abort or failure",
            "### Unit abort or live-validation cancellation",
            "### Rotation",
            "### Complete deletion",
            "### Compromise",
        ):
            self.assertIn(heading, self.runbook)
        for credential in CREDENTIALS:
            path = f"{SOURCE_DIRECTORY}/{credential}"
            self.assertIn(path, self.runbook)
            self.assertIn(path + ".new", self.runbook)
        self.assertIn(
            "/run/systemd/transient/" "tradingai-ai-advisor-live-validation.service",
            self.runbook,
        )

    def test_all_operational_documents_use_the_same_unit_and_namespace(self):
        for document in self.documents:
            self.assertIn(UNIT_NAME, document)
            self.assertIn(SOURCE_DIRECTORY, document)
            self.assertNotIn("systemd-run --pty", document)

    def test_safe_result_metadata_and_fail_closed_sanitizer_are_documented(self):
        for field in (
            "request_id",
            "model",
            "provider",
            "endpoint_classification",
        ):
            self.assertIn(field, self.runbook)
        self.assertIn("official SDK", self.runbook)
        self.assertIn("official_openai", self.runbook)
        self.assertIn("SAFE_IDENTIFIER", self.runbook)
        self.assertIn("FORBIDDEN_IDENTIFIER_PREFIXES", self.runbook)
        self.assertIn("UNSAFE_OR_UNKNOWN_FIELD_REJECTED", self.runbook)
        self.assertIn(
            "This offline contract change is not Live authorization",
            self.runbook,
        )

    def test_existing_runner_preflight_is_structured_and_independent(self):
        self.assertNotIn("if pgrep -f", self.runbook)
        self.assertIn("Standalone `pgrep -f` is prohibited", self.runbook)
        self.assertIn(
            "-m backend.ai_advisor.runner_process_detection",
            self.runbook,
        )
        normalized_runbook = " ".join(self.runbook.split())
        for contract in (
            "independent command",
            "separate Live command",
            "fixed transient-unit metadata is the primary signal",
            "NUL-delimited argv vector",
            "`-m backend.ai_advisor.isolated_smoke_runner`",
            "own PID and parent PID",
            "Python `-c`",
            "`INDETERMINATE`",
            "secret-free reason code",
            "RUNNER_ABSENT reason=<SAFE_CODE>",
            "Clearly non-Python processes",
            "without reading their executable or cmdline",
            "standalone helper diagnostic is not a Live Validation",
            "Never kill an existing or suspected Runner",
            "does not authorize Live execution",
            "new explicit approval",
        ):
            self.assertIn(contract, normalized_runbook)

    def test_documented_sanitizer_accepts_only_exact_safe_metadata(self):
        marker = "cat >\"$SANITIZER\" <<'PY'\n"
        script = self.runbook.split(marker, 1)[1].split(
            "\nPY\n\n# Prerequisite:",
            1,
        )[0]
        safe = {
            "mode": "DRY_RUN",
            "status": "READY_FOR_CONFIGURATION",
            "compositionBuilt": True,
            "liveInvocationAttempted": False,
            "invocationSucceeded": False,
            "maximumProviderCalls": 1,
            "providerRequestUpperBound": 1,
            "retryPerformed": False,
            "request_id": None,
            "model": None,
            "provider": None,
            "endpoint_classification": None,
            "failureStage": None,
            "httpStatus": None,
            "parseSucceeded": None,
            "validationCode": None,
            "topLevelType": None,
            "invalidField": None,
            "missingFields": [],
            "usageStatus": "USAGE_UNAVAILABLE",
            "usage": None,
            "safeReasons": ["DRY_RUN_COMPLETE"],
        }

        recovered = subprocess.run(
            [sys.executable, "-c", script],
            input=json.dumps(safe) + "\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(recovered.returncode, 0)
        self.assertEqual(
            json.loads(recovered.stdout)["recoveryStatus"],
            "RECOVERED",
        )

        for unsafe in (
            {**safe, "unknownField": "private response"},
            {**safe, "request_id": "sk-" + "A" * 40},
        ):
            with self.subTest(fields=tuple(unsafe)):
                rejected = subprocess.run(
                    [sys.executable, "-c", script],
                    input=json.dumps(unsafe) + "\n",
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(rejected.returncode, 22)
                projection = json.loads(rejected.stdout)
                self.assertEqual(
                    projection["recoveryStatus"],
                    "UNSAFE_OR_UNKNOWN_FIELD_REJECTED",
                )
                self.assertEqual(projection["safeProjection"], {})


if __name__ == "__main__":
    unittest.main()
