import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNIT_NAME = "tradingai-ai-advisor-live-validation.service"
UNIT = ROOT / (
    "deploy/systemd/"
    "tradingai-ai-advisor-live-validation.service"
)
RUNBOOK = ROOT / "docs/ai_advisor/systemd-credential-smoke-runbook.md"
MATRIX = ROOT / "docs/ai_advisor/PRODUCTION_CONFIGURATION_MATRIX_CANDIDATE.md"
READINESS = ROOT / "docs/ai_advisor/FINAL_OFFLINE_PRODUCTION_READINESS_PACKAGE.md"
PRODUCTION_RUNBOOK = ROOT / "docs/ai_advisor/AI_ADV_1F_BATCH2_PRODUCTION_RUNBOOK.md"
SOURCE_DIRECTORY = (
    "/etc/credstore.encrypted/tradingai-ai-advisor-live-validation"
)
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
            self.unit.count(
                "'AI-ADV-1E9 LIVE TEST APPROVED: ONE REQUEST'"
            ),
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
            "/run/systemd/transient/"
            "tradingai-ai-advisor-live-validation.service",
            self.runbook,
        )

    def test_all_operational_documents_use_the_same_unit_and_namespace(self):
        for document in self.documents:
            self.assertIn(UNIT_NAME, document)
            self.assertIn(SOURCE_DIRECTORY, document)
            self.assertNotIn("systemd-run --pty", document)


if __name__ == "__main__":
    unittest.main()
