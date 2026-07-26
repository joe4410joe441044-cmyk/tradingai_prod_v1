# -*- coding: utf-8 -*-
"""Legacy Telegram-coupled entrypoint.

Telegram integration is intentionally disabled. This module performs no
credential resolution, consumer construction, or network activity.
"""

TELEGRAM_INTEGRATION_ENABLED = False


def main():
    """Return a fixed successful result while Telegram remains disabled."""
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
