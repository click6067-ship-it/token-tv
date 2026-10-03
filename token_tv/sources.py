"""Use credentials in their owning CLI homes; export only approved fields."""
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from token_tv.usage import normalize_claude, normalize_codex, normalize_grok, timestamp, window
from token_tv.display import STYLES


class SourceError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def scoped_env(provider, root):
    env = dict(os.environ)
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN",
                "GROK_OAUTH_TOKEN", "GROK_API_KEY", "XAI_API_KEY", "GROK_AUTH_TOKEN", "CLAUDECODE"):
        env.pop(key, None)
    variable = {"claude": "CLAUDE_CONFIG_DIR", "codex": "CODEX_HOME", "grok": "GROK_HOME"}[provider]
    env[variable] = str(root)
    if provider == "claude":
        env["CLAUDE_SECURESTORAGE_CONFIG_DIR"] = str(root)
    return env


class RPC:
    def __init__(self, command, env):
        self.process = subprocess.Popen(command, env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        text=True, bufsize=1)
        self.messages = queue.Queue()
        self.sequence = 0
        def read():
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except ValueError:
                    continue
            self.messages.put(None)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def call(self, method, params=None, timeout=25):
        self.sequence += 1
        identifier = self.sequence
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": identifier,
                                            "method": method, "params": params or {}}) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SourceError("timeout")
            try:
                reply = self.messages.get(timeout=remaining)
            except queue.Empty:
                raise SourceError("timeout") from None
            if reply is None:
                raise SourceError("cli_unavailable")
            if reply.get("id") != identifier:
                # This client never permits agent tool execution.
                if "method" in reply and "id" in reply:
                    self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": reply["id"],
                                                        "error": {"code": -32601, "message": "Not supported"}}) + "\n")
                    self.process.stdin.flush()
                continue
            if "error" in reply:
                error = reply["error"]
                message = str(error.get("message", "")).lower()
                code = "auth_required" if any(x in message for x in ("auth", "login", "sign in", "token")) else "rpc_error"
                if error.get("code") == -32601:
                    code = "method_unavailable"
                raise SourceError(code)
            return reply.get("result") or {}

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        for stream in (self.process.stdin, self.process.stdout):
            stream.close()
        self.reader.join(timeout=1)


def load_config(path):
    data = json.loads(Path(path).read_text())
    if set(data) - {"accounts", "device_url", "poll_seconds", "font", "display_style"}:
        raise ValueError("Unsupported configuration field")
    if data.get('display_style', 'pixel') not in STYLES:
        raise ValueError('Unknown display style')
    seen = set()
    allowed = {"key", "alias", "provider", "source_home", "email", "snapshot_file", "fallback_snapshot_file", "refresh_with_cli"}
    for account in data.get("accounts", []):
        if set(account) - allowed:
            raise ValueError("Only credential-free account metadata is allowed")
        if account.get("provider") not in ("claude", "codex", "grok"):
            raise ValueError("Unknown provider")
        key = account.get("key", "")
        if not re.fullmatch(r"[a-z0-9_-]{1,48}", key) or key in seen:
            raise ValueError("Account keys must be unique")
        if not isinstance(account.get("alias"), str) or not 1 <= len(account["alias"]) <= 32:
            raise ValueError("Account alias is required")
        if not account.get("email"):
            raise ValueError("Expected account identity is required")
        seen.add(key)
    if not seen:
        raise ValueError("At least one account is required")
    return data


def json_get(url, headers=None):
    with urlopen(Request(url, headers=headers or {}), timeout=20) as response:
        return json.load(response)


def keychain_services(root):
    """macOS Keychain item names Claude Code uses for a CLI home (read from Claude Code 2.1.281)."""
    home = str(root)
    services = ["Claude Code-credentials-" + hashlib.sha256(unicodedata.normalize("NFC", home).encode()).hexdigest()[:8]]
    if root == Path("~/.claude").expanduser():
        services.append("Claude Code-credentials")
    return services


def claude_token(root):
    """Access token from the CLI home's file, or on macOS from the login Keychain (read only)."""
    path = root / ".credentials.json"
    if path.is_file() or sys.platform != "darwin":
        return json.loads(path.read_text())["claudeAiOauth"]["accessToken"]
    user = os.environ.get("USER") or "claude-code-user"
    for service in keychain_services(root):
        result = subprocess.run(["security", "find-generic-password", "-a", user, "-w", "-s", service],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)["claudeAiOauth"]["accessToken"]
    raise SourceError("auth_required")


def claude_payload(account):
    root = Path(account["source_home"]).expanduser()
    token = claude_token(root)
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json",
               "User-Agent": "claude-code/2.1.287", "anthropic-beta": "oauth-2025-04-20"}
    try:
        profile = json_get("https://api.anthropic.com/api/oauth/profile", headers)
        usage = json_get("https://api.anthropic.com/api/oauth/usage", headers)
    except HTTPError as error:
        if error.code != 401 or not account.get("refresh_with_cli"):
            raise
        # The CLI owns refresh/rotation. No manual refresh-token writes.
        env = scoped_env("claude", root)
        subprocess.run(["claude", "-p", "Reply only OK.", "--tools", "",
                        "--no-session-persistence", "--max-turns", "1"],
                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=60)
        token = claude_token(root)
        headers["Authorization"] = "Bearer " + token
        profile = json_get("https://api.anthropic.com/api/oauth/profile", headers)
        usage = json_get("https://api.anthropic.com/api/oauth/usage", headers)
    return profile, usage


def email_from_profile(profile):
    for item in (profile.get("account") or {}, profile):
        for key in ("emailAddress", "email_address", "email"):
            if isinstance(item.get(key), str):
                return item[key]
    return None


def identity_matches(expected, actual):
    return bool(actual and expected.strip().casefold() == actual.strip().casefold())


def codex_payload(account):
    if not (Path(account["source_home"]).expanduser() / "auth.json").is_file():
        raise SourceError("auth_required")
    env = scoped_env("codex", Path(account["source_home"]).expanduser())
    rpc = RPC(["codex", "app-server"], env)
    try:
        rpc.call("initialize", {"clientInfo": {"name": "token_tv", "title": "TokenTV", "version": "0.1.0"}, "capabilities": {}})
        rpc.process.stdin.write('{"method":"initialized","params":{}}\n')
        rpc.process.stdin.flush()
        identity = rpc.call("account/read", {"refreshToken": True}).get("account") or {}
        if identity.get("type") != "chatgpt":
            raise SourceError("auth_required")
        if not identity_matches(account["email"], identity.get("email")):
            raise SourceError("identity_mismatch")
        return rpc.call("account/rateLimits/read")
    finally:
        rpc.close()


def grok_payload(account):
    root = Path(account["source_home"]).expanduser()
    if not (root / "auth.json").is_file():
        raise SourceError("auth_required")
    env = scoped_env("grok", root)
    command = os.environ.get("TOKEN_TV_GROK_BIN", "grok")
    rpc = RPC([command, "agent", "--no-leader", "stdio"], env)
    try:
        rpc.call("initialize", {"protocolVersion": 1, "clientCapabilities": {
            "fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}})
        try:
            return rpc.call("_x.ai/billing", timeout=20)
        except SourceError as error:
            if error.code != "method_unavailable":
                raise
            return rpc.call("x.ai/billing", timeout=20)
    finally:
        rpc.close()


def grok_identity(account):
    data = json.loads((Path(account["source_home"]).expanduser() / "auth.json").read_text())
    emails = set()
    def scan(value):
        if isinstance(value, dict):
            if isinstance(value.get("email"), str):
                emails.add(value["email"].strip().casefold())
            for item in value.values():
                if isinstance(item, (dict, list)):
                    scan(item)
        elif isinstance(value, list):
            for item in value:
                scan(item)
    scan(data)
    if len(emails) != 1:
        raise SourceError("identity_mismatch")
    return emails.pop()


def imported_row(account):
    data = json.loads(Path(account["snapshot_file"]).expanduser().read_text())
    row = data["accounts"][account["key"]]
    if row.get("provider") != account["provider"] or row.get("alias") != account["alias"]:
        raise SourceError("identity_mismatch")
    fetched = timestamp(row.get("fetched_at"))
    if fetched is None or fetched > time.time() + 60:
        raise SourceError("invalid_snapshot")
    allowed_status = {"ok", "quota_unavailable", "auth_required", "identity_mismatch", "error", "rate_limited", "stale"}
    if row.get("status") not in allowed_status:
        raise SourceError("invalid_snapshot")
    clean = {"key": account["key"], "alias": account["alias"], "provider": account["provider"],
             "status": row["status"], "windows": [], "fetched_at": fetched,
             "identity_verified": row.get("identity_verified") is True, "source": "laptop"}
    last_success = timestamp(row.get("last_success_at"))
    if last_success and last_success <= fetched:
        clean["last_success_at"] = last_success
    for value in row.get("windows", []):
        if value.get("label") not in {"5H", "WEEK", "WINDOW", "BUDGET"}:
            continue
        item = window(value["label"], value.get("used_percent"), value.get("resets_at"),
                      value.get("duration_minutes"))
        if item:
            clean["windows"].append(item)
    if time.time() - fetched > 900:
        clean["status"] = "stale"
        clean["error_code"] = "laptop_offline"
    return clean


def fetch_account(account):
    row = {"key": account["key"], "alias": account["alias"], "provider": account["provider"],
           "status": "auth_required", "windows": [], "fetched_at": time.time(),
           "identity_verified": False, "source": "mini"}
    try:
        if account.get("snapshot_file"):
            return imported_row(account)
        if account["provider"] == "claude":
            profile, data = claude_payload(account)
            if not identity_matches(account["email"], email_from_profile(profile)):
                raise SourceError("identity_mismatch")
            row["windows"] = normalize_claude(data)
            row["identity_verified"] = True
        elif account["provider"] == "codex":
            row["windows"] = normalize_codex(codex_payload(account))
            row["identity_verified"] = True
        else:
            if not identity_matches(account["email"], grok_identity(account)):
                raise SourceError("identity_mismatch")
            data = grok_payload(account)
            row["windows"] = normalize_grok(data)
            row["identity_verified"] = True
        row["status"] = "ok" if row["windows"] else "quota_unavailable"
    except SourceError as error:
        row["status"] = error.code if error.code in {"auth_required", "identity_mismatch", "stale"} else "error"
        row["error_code"] = error.code
    except HTTPError as error:
        row["status"] = {401: "auth_required", 403: "auth_required", 429: "rate_limited"}.get(error.code, "error")
        row["error_code"] = "http_" + str(error.code)
    except FileNotFoundError:
        row["status"] = "auth_required"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        row["status"] = "error"
        row["error_code"] = "source_unavailable"
    row["fetched_at"] = time.time()
    if row["status"] not in {"ok", "quota_unavailable", "identity_mismatch"} and account.get("fallback_snapshot_file"):
        try:
            fallback = imported_row(dict(account, snapshot_file=account["fallback_snapshot_file"]))
            fallback["mini_auth_status"] = row["status"]
            return fallback
        except (SourceError, OSError, ValueError, KeyError, TypeError):
            pass
    return row
