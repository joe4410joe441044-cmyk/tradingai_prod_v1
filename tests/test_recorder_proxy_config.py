# -*- coding: utf-8 -*-
"""Configuration contract tests for the read-only Market Recorder proxy."""

import unittest

from backend.config.recorder_proxy import (
    RecorderProxyConfigError,
    load_recorder_proxy_config,
)


class RecorderProxyConfigTests(unittest.TestCase):
    def test_disabled_when_enabled_flag_missing(self):
        config = load_recorder_proxy_config({})
        self.assertFalse(config.enabled)
        self.assertEqual(config.base_url, "")

    def test_disabled_when_enabled_flag_false(self):
        config = load_recorder_proxy_config({"RECORDER_API_ENABLED": "false"})
        self.assertFalse(config.enabled)

    def test_enabled_requires_base_url(self):
        with self.assertRaises(RecorderProxyConfigError):
            load_recorder_proxy_config({"RECORDER_API_ENABLED": "true"})

    def test_enabled_rejects_non_http_scheme(self):
        with self.assertRaises(RecorderProxyConfigError):
            load_recorder_proxy_config(
                {
                    "RECORDER_API_ENABLED": "true",
                    "RECORDER_API_BASE_URL": "ftp://example.com",
                }
            )

    def test_enabled_rejects_embedded_credentials(self):
        with self.assertRaises(RecorderProxyConfigError):
            load_recorder_proxy_config(
                {
                    "RECORDER_API_ENABLED": "true",
                    "RECORDER_API_BASE_URL": "http://user:pass@example.com",
                }
            )

    def test_enabled_rejects_query_in_base_url(self):
        with self.assertRaises(RecorderProxyConfigError):
            load_recorder_proxy_config(
                {
                    "RECORDER_API_ENABLED": "true",
                    "RECORDER_API_BASE_URL": "http://example.com?token=secret",
                }
            )

    def test_enabled_rejects_fragment_in_base_url(self):
        with self.assertRaises(RecorderProxyConfigError):
            load_recorder_proxy_config(
                {
                    "RECORDER_API_ENABLED": "true",
                    "RECORDER_API_BASE_URL": "http://example.com#section",
                }
            )

    def test_enabled_rejects_path_in_base_url(self):
        with self.assertRaises(RecorderProxyConfigError):
            load_recorder_proxy_config(
                {
                    "RECORDER_API_ENABLED": "true",
                    "RECORDER_API_BASE_URL": "http://example.com/api/recorder",
                }
            )

    def test_enabled_normalizes_trailing_slash(self):
        config = load_recorder_proxy_config(
            {
                "RECORDER_API_ENABLED": "true",
                "RECORDER_API_BASE_URL": "http://example.com/",
            }
        )
        self.assertTrue(config.enabled)
        self.assertEqual(config.base_url, "http://example.com")

    def test_timeout_parsed_and_validated(self):
        config = load_recorder_proxy_config(
            {
                "RECORDER_API_ENABLED": "true",
                "RECORDER_API_BASE_URL": "http://example.com",
                "RECORDER_API_TIMEOUT": "3.5",
            }
        )
        self.assertEqual(config.timeout_seconds, 3.5)
        with self.assertRaises(RecorderProxyConfigError):
            load_recorder_proxy_config(
                {
                    "RECORDER_API_ENABLED": "true",
                    "RECORDER_API_BASE_URL": "http://example.com",
                    "RECORDER_API_TIMEOUT": "-1",
                }
            )
        with self.assertRaises(RecorderProxyConfigError):
            load_recorder_proxy_config(
                {
                    "RECORDER_API_ENABLED": "true",
                    "RECORDER_API_BASE_URL": "http://example.com",
                    "RECORDER_API_TIMEOUT": "abc",
                }
            )

    def test_default_timeout_when_unset(self):
        config = load_recorder_proxy_config(
            {
                "RECORDER_API_ENABLED": "true",
                "RECORDER_API_BASE_URL": "http://example.com",
            }
        )
        self.assertEqual(config.timeout_seconds, 5.0)

    def test_verify_tls_parse(self):
        config = load_recorder_proxy_config(
            {
                "RECORDER_API_ENABLED": "true",
                "RECORDER_API_BASE_URL": "http://example.com",
                "RECORDER_API_VERIFY_TLS": "false",
            }
        )
        self.assertFalse(config.verify_tls)
        with self.assertRaises(RecorderProxyConfigError):
            load_recorder_proxy_config(
                {
                    "RECORDER_API_ENABLED": "true",
                    "RECORDER_API_BASE_URL": "http://example.com",
                    "RECORDER_API_VERIFY_TLS": "maybe",
                }
            )

    def test_config_error_message_is_generic(self):
        try:
            load_recorder_proxy_config(
                {
                    "RECORDER_API_ENABLED": "true",
                    "RECORDER_API_BASE_URL": "ftp://secret-host.internal.example",
                }
            )
            self.fail("expected config error")
        except RecorderProxyConfigError as error:
            rendered = str(error)
            self.assertNotIn("secret-host", rendered)

    def test_invalid_enabled_flag_fails_closed(self):
        with self.assertRaises(RecorderProxyConfigError):
            load_recorder_proxy_config({"RECORDER_API_ENABLED": "maybe"})

    def test_empty_enabled_flag_fails_closed(self):
        with self.assertRaises(RecorderProxyConfigError):
            load_recorder_proxy_config({"RECORDER_API_ENABLED": ""})

    def test_empty_base_url_rejected(self):
        with self.assertRaises(RecorderProxyConfigError):
            load_recorder_proxy_config(
                {
                    "RECORDER_API_ENABLED": "true",
                    "RECORDER_API_BASE_URL": "",
                }
            )

    def test_zero_timeout_rejected(self):
        with self.assertRaises(RecorderProxyConfigError):
            load_recorder_proxy_config(
                {
                    "RECORDER_API_ENABLED": "true",
                    "RECORDER_API_BASE_URL": "http://example.com",
                    "RECORDER_API_TIMEOUT": "0",
                }
            )

    def test_verify_tls_defaults_to_true_when_unset(self):
        config = load_recorder_proxy_config(
            {
                "RECORDER_API_ENABLED": "true",
                "RECORDER_API_BASE_URL": "http://example.com",
            }
        )
        self.assertTrue(config.verify_tls)

    def test_verify_tls_accepts_boolean_aliases(self):
        config = load_recorder_proxy_config(
            {
                "RECORDER_API_ENABLED": "true",
                "RECORDER_API_BASE_URL": "http://example.com",
                "RECORDER_API_VERIFY_TLS": "1",
            }
        )
        self.assertTrue(config.verify_tls)
        config = load_recorder_proxy_config(
            {
                "RECORDER_API_ENABLED": "true",
                "RECORDER_API_BASE_URL": "http://example.com",
                "RECORDER_API_VERIFY_TLS": "off",
            }
        )
        self.assertFalse(config.verify_tls)


if __name__ == "__main__":
    unittest.main()
