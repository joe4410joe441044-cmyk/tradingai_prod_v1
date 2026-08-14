"""Runtime contract tests for systemd and nginx repository templates.

Validates that repository templates match the verified Contabo runtime contract
without requiring the services to be running.

- No legacy GCP paths (TradingAI_Bot_Prod_v1)
- No legacy GCP IPs (35.194.104.74, 34.85.66.137)
- Backend bound to 127.0.0.1:8001 only
- nginx upstream is 127.0.0.1:8001
- nginx has no TLS/port 443
- WebSocket upgrade directives present
- Sensitive-path denials present
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GCP_IPS = re.compile(r"35\.194\.104\.74|34\.85\.66\.137")
GCP_PATHS = re.compile(r"TradingAI_Bot_Prod_v1")
PUBLIC_BIND = re.compile(r"0\.0\.0\.0:8001")


class SystemdTemplateContractTest(unittest.TestCase):
    def setUp(self):
        self.unit = (ROOT / "systemd/tradingbot.service").read_text(encoding="utf-8")
        self.lines = [
            line.strip()
            for line in self.unit.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    def test_no_legacy_gcp_ip(self):
        self.assertIsNone(GCP_IPS.search(self.unit))

    def test_no_legacy_gcp_path(self):
        self.assertIsNone(GCP_PATHS.search(self.unit))

    def test_user_is_joe4410joe(self):
        self.assertIn("User=joe4410joe", self.lines)

    def test_group_is_joe4410joe(self):
        self.assertIn("Group=joe4410joe", self.lines)

    def test_working_directory_is_tradingai_prod_v1(self):
        self.assertIn(
            "WorkingDirectory=/home/joe4410joe/tradingai_prod_v1", self.lines
        )

    def test_exec_start_uses_correct_venv(self):
        self.assertTrue(
            any(
                "/home/joe4410joe/tradingai_prod_v1/venv/bin/python" in line
                for line in self.lines
            )
        )

    def test_exec_start_binds_loopback_port_8001(self):
        self.assertTrue(
            any(
                "127.0.0.1" in line and "8001" in line
                for line in self.lines
            )
        )

    def test_no_public_bind_0_0_0_0(self):
        self.assertNotIn("0.0.0.0", self.unit)

    def test_restart_always(self):
        self.assertIn("Restart=always", self.lines)

    def test_restart_sec_5(self):
        self.assertIn("RestartSec=5", self.lines)

    def test_standard_output_journal(self):
        self.assertIn("StandardOutput=journal", self.lines)

    def test_standard_error_journal(self):
        self.assertIn("StandardError=journal", self.lines)

    def test_umask_0077(self):
        self.assertIn("UMask=0077", self.lines)

    def test_wanted_by_multi_user(self):
        self.assertIn("WantedBy=multi-user.target", self.lines)

    def test_no_legacy_run_prod_py(self):
        self.assertNotIn("run_prod.py", self.unit)

    def test_no_hardcoded_telegram_token(self):
        self.assertFalse(
            any(
                line.startswith("Environment=") and "TELEGRAM" in line
                for line in self.lines
            )
        )


class NginxTemplateContractTest(unittest.TestCase):
    def setUp(self):
        self.nginx = (ROOT / "deploy/nginx-tradingai.conf").read_text(encoding="utf-8")
        self.lines = [
            line.strip()
            for line in self.nginx.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    def test_no_legacy_gcp_ip(self):
        self.assertIsNone(GCP_IPS.search(self.nginx))

    def test_no_legacy_gcp_path(self):
        self.assertIsNone(GCP_PATHS.search(self.nginx))

    def test_listens_port_80(self):
        self.assertTrue(any("listen 80" in line for line in self.lines))

    def test_no_port_443_listener(self):
        self.assertFalse(any("listen 443" in line for line in self.lines))
        self.assertFalse(any("listen [::]:443" in line for line in self.lines))

    def test_no_ssl_directive(self):
        unified = " ".join(self.lines)
        self.assertNotIn("ssl_certificate", unified)
        self.assertNotIn("ssl on", unified)
        self.assertFalse(any("ssl_protocols" in line for line in self.lines))

    def test_upstream_is_loopback_8001(self):
        proxy_lines = [l for l in self.lines if "proxy_pass" in l]
        self.assertTrue(proxy_lines)
        for line in proxy_lines:
            self.assertIn("127.0.0.1:8001", line)

    def test_no_public_upstream(self):
        self.assertNotIn("proxy_pass http://169.58.111.142", self.nginx)
        self.assertNotIn("proxy_pass http://0.0.0.0", self.nginx)

    def test_frontend_root_is_dist(self):
        self.assertTrue(
            any(
                "tradingai_prod_v1/frontend/dist" in line
                for line in self.lines
            )
        )

    def test_spa_fallback(self):
        self.assertTrue(
            any("try_files $uri $uri/ /index.html" in line for line in self.lines)
        )

    def test_api_location_preserves_prefix(self):
        proxy_line = None
        api_section = False
        for line in self.lines:
            if "location /api/" in line:
                api_section = True
            if api_section and "proxy_pass" in line and "/api/" not in line:
                proxy_line = line
                break
        self.assertIsNotNone(proxy_line, "API proxy_pass not found")

    def test_config_location_exact(self):
        self.assertTrue(any("= /config" in line for line in self.lines))

    def test_websocket_upgrade_headers(self):
        self.assertTrue(any("Upgrade $http_upgrade" in line for line in self.lines))
        self.assertTrue(
            any('Connection "upgrade"' in line for line in self.lines)
        )

    def test_websocket_http_version_1_1(self):
        ws_section = False
        for line in self.lines:
            if "location /ws" in line:
                ws_section = True
            if ws_section and "proxy_http_version 1.1" in line:
                return
        self.fail("WebSocket proxy_http_version 1.1 not found")

    def test_sensitive_path_denials(self):
        self.assertTrue(any("return 404" in line and ".env" in line for line in self.lines))
        self.assertTrue(any("return 404" in line and ".git" in line for line in self.lines))

    def test_no_directory_listing(self):
        self.assertTrue(
            any("autoindex off" in line for line in self.lines)
        )

    def test_assets_immutable_cache(self):
        self.assertTrue(
            any("immutable" in line and "Cache-Control" in line for line in self.lines)
        )


class NginxDuplicateTemplateConsistencyTest(unittest.TestCase):
    def setUp(self):
        canonical = (ROOT / "deploy/nginx-tradingai.conf").read_text(encoding="utf-8")
        duplicate = (ROOT / "frontend/tradingai.conf").read_text(encoding="utf-8")

        def normalize(text):
            return re.sub(r"#.*", "", text)
            # strip comments

        self.canonical_directives = self._extract_directives(normalize(canonical))
        self.duplicate_directives = self._extract_directives(normalize(duplicate))

    @staticmethod
    def _extract_directives(text):
        directives = set()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                key = re.sub(r"\s+", " ", stripped)
                directives.add(key)
        return directives

    def test_core_proxy_locations_match(self):
        for d in ["listen 80;", "proxy_pass http://127.0.0.1:8001;",
                   'proxy_set_header Upgrade $http_upgrade;',
                   'proxy_set_header Connection "upgrade";',
                   "proxy_http_version 1.1;"]:
            self.assertIn(d, self.canonical_directives)
            self.assertIn(d, self.duplicate_directives)

    def test_duplicate_has_no_gcp_ips(self):
        text = (ROOT / "frontend/tradingai.conf").read_text(encoding="utf-8")
        self.assertIsNone(GCP_IPS.search(text))


if __name__ == "__main__":
    unittest.main()
