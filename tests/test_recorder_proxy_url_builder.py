# -*- coding: utf-8 -*-
"""URL builder tests for the read-only Market Recorder proxy."""

import unittest

from backend.services.http.recorder_url_builder import (
    ENDPOINT_PATHS,
    RecorderProxyURLBuilderError,
    build_upstream_url,
    normalize_base_url,
)


class RecorderProxyURLBuilderTests(unittest.TestCase):
    def test_builds_known_endpoints(self):
        self.assertEqual(
            build_upstream_url("http://recorder.example.com", "health"),
            "http://recorder.example.com/api/recorder/health",
        )
        self.assertEqual(
            build_upstream_url("https://recorder.example.com", "status"),
            "https://recorder.example.com/api/recorder/status",
        )
        self.assertEqual(
            build_upstream_url("http://recorder.example.com", "storage"),
            "http://recorder.example.com/api/recorder/storage",
        )
        self.assertEqual(
            build_upstream_url("http://recorder.example.com", "archives"),
            "http://recorder.example.com/api/recorder/archives",
        )

    def test_endpoint_path_allowlist_is_fixed(self):
        self.assertEqual(
            set(ENDPOINT_PATHS),
            {"health", "status", "storage", "archives", "start", "stop"},
        )

    def test_unknown_endpoint_rejected(self):
        with self.assertRaises(RecorderProxyURLBuilderError):
            build_upstream_url("http://recorder.example.com", "upload")

    def test_client_path_never_accepted(self):
        with self.assertRaises(RecorderProxyURLBuilderError):
            build_upstream_url(
                "http://recorder.example.com",
                "../../../etc/passwd",
            )

    def test_base_url_requires_http_https(self):
        with self.assertRaises(RecorderProxyURLBuilderError):
            normalize_base_url("ftp://recorder.example.com")
        with self.assertRaises(RecorderProxyURLBuilderError):
            normalize_base_url("file:///etc/passwd")

    def test_base_url_rejects_query_and_fragment(self):
        with self.assertRaises(RecorderProxyURLBuilderError):
            normalize_base_url("http://recorder.example.com?target=http://evil")
        with self.assertRaises(RecorderProxyURLBuilderError):
            normalize_base_url("http://recorder.example.com#target")

    def test_base_url_rejects_credentials(self):
        with self.assertRaises(RecorderProxyURLBuilderError):
            normalize_base_url("http://user:pass@recorder.example.com")

    def test_trailing_slash_normalized(self):
        self.assertEqual(
            normalize_base_url("http://recorder.example.com/"),
            "http://recorder.example.com",
        )

    def test_builder_normalizes_trailing_slash(self):
        self.assertEqual(
            build_upstream_url("https://recorder.example.com/", "health"),
            "https://recorder.example.com/api/recorder/health",
        )

    def test_missing_base_url_rejected(self):
        with self.assertRaises(RecorderProxyURLBuilderError):
            normalize_base_url("")
        with self.assertRaises(RecorderProxyURLBuilderError):
            normalize_base_url(None)


if __name__ == "__main__":
    unittest.main()
