"""Sign in to one account's Mini-local CLI home, without changing defaults."""
import argparse
import os
import subprocess
from pathlib import Path

from token_tv.sources import fetch_account, load_config, scoped_env


def login_command(account, browser=False):
    provider = account["provider"]
    if provider == "claude":
        return ["claude", "auth", "login", "--claudeai", "--email", account["email"]]
    if provider == "codex":
        return ["codex", "login"] if browser else ["codex", "login", "--device-auth"]
    return [os.environ.get("TOKEN_TV_GROK_BIN", "grok"), "login", "--device-auth"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--account", help="Stable account key; omit to choose interactively")
    parser.add_argument("--browser", action="store_true", help="Use Codex browser login (forward localhost:1455 when running over SSH)")
    args = parser.parse_args()
    accounts = load_config(args.config)["accounts"]
    key = args.account
    if key is None:
        for index, account in enumerate(accounts, 1):
            print(f"{index}. {account['provider']} · {account['alias']}")
        try:
            choice = int(input("Choose account number: "))
            if not 1 <= choice <= len(accounts):
                raise ValueError("Out of range")
            key = accounts[choice - 1]["key"]
        except (ValueError, IndexError, EOFError):
            parser.error("Choose one of the listed accounts")
    account = next((a for a in accounts if a["key"] == key), None)
    if account is None or not account.get("source_home"):
        parser.error("An account with a Mini-local CLI home is required")
    root = Path(account["source_home"]).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    print("Sign in as " + account["email"] + ". Enter login codes here, not in chat.", flush=True)
    result = subprocess.run(login_command(account, args.browser), env=scoped_env(account["provider"], root))
    if result.returncode:
        raise SystemExit(result.returncode)
    # Verification must use the newly authenticated source, never its fallback.
    direct = {k: v for k, v in account.items() if k not in ("snapshot_file", "fallback_snapshot_file")}
    row = fetch_account(direct)
    print("Verification: " + row["status"], flush=True)
    if row["status"] not in ("ok", "quota_unavailable") or not row["identity_verified"]:
        raise SystemExit(1)
    print("Account verified. The running Mini display will use this login on its next poll.", flush=True)


if __name__ == "__main__":
    main()
