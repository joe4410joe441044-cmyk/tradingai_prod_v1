#!/usr/bin/env python3
"""Run the CC-4A loopback-only synthetic evaluation boundary."""

from backend.prop_trading.offline_server import HOST, PORT, create_server


def main() -> int:
    server = create_server()
    print(f"CC-4A offline synthetic evaluator: http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
