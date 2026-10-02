import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from token_tv.providers.base import Account, Provider, Usage
from token_tv.providers.mock import MockProvider


MOCK_ACCOUNTS = (
    Account("claude_personal", "Claude personal", "claude"),
    Account("claude_work", "Claude work", "claude"),
    Account("codex_personal", "Codex personal", "codex"),
)


def build_snapshot(accounts: tuple[Account, ...], providers: dict[str, Provider]) -> dict:
    result = {}
    for account in accounts:
        try:
            usage = providers[account.provider].fetch(account)
        except (KeyError, OSError, ValueError):
            usage = Usage("error", None, None, None, None)
        result[account.key] = {
            "alias": account.alias,
            "provider": account.provider,
            "status": usage.status,
            "session_percent": usage.session_percent,
            "session_reset_minutes": usage.session_reset_minutes,
            "weekly_percent": usage.weekly_percent,
            "weekly_reset_minutes": usage.weekly_reset_minutes,
        }
    return {"schema": 1, "accounts": result}


def make_handler(accounts: tuple[Account, ...], providers: dict[str, Provider]):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/snapshot":
                data = build_snapshot(accounts, providers)
            elif self.path.startswith("/snapshot/"):
                key = self.path.removeprefix("/snapshot/")
                account = next((item for item in accounts if item.key == key), None)
                if account is None:
                    self.send_error(404)
                    return
                data = build_snapshot((account,), providers)["accounts"][key]
            else:
                self.send_error(404)
                return
            body = json.dumps(data, separators=(",", ":")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="TokenTV mock usage daemon")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    with ThreadingHTTPServer((args.host, args.port), make_handler(MOCK_ACCOUNTS, {
        "claude": MockProvider(),
        "codex": MockProvider(),
    })) as server:
        print(f"TokenTV mock listening at http://{args.host}:{server.server_port}/snapshot", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
