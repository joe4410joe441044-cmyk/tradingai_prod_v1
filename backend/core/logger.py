"""Shared application logger.

The handler configuration lives in ``backend.utils.log_buffer`` so importing
this compatibility module cannot replace the rotating file handler with an
unbounded stdout handler.
"""

from backend.utils.log_buffer import logger
