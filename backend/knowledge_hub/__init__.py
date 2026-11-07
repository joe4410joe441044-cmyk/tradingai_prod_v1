"""Isolated read-only collectors for the Unified Knowledge Hub.

Importing this package does not scan the filesystem, run Git, register a
runtime hook, or contact Advisor, Supervisor, or an exchange.
"""

SCHEMA_VERSION = "tradingai-knowledge-collector/v1"

__all__ = ["SCHEMA_VERSION"]
