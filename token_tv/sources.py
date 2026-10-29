"""Use credentials in their owning CLI homes; export only approved fields."""
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

from token_tv import __version__
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from token_tv.usage import (normalize_claude, normalize_codex, normalize_codexbar, normalize_grok, reset_credits, timestamp,
                             window)
from token_tv.display import STYLES

CODEXBAR_SOURCES = {"auto", "web", "cli", "oauth", "api"}
AUTH_WORDS = ("auth", "login", "sign in", "token")


def exe(name):
    """Full path of a CLI. On Windows npm installs `claude`/`codex` as .cmd shims that a bare name can't start."""
    return shutil.which(name) or name


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
                code = "auth_required" if any(x in message for x in AUTH_WORDS) else "rpc_error"
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
    allowed = {"key", "alias", "provider", "source_home", "email", "snapshot_file", "fallback_snapshot_file", "refresh_with_cli",
               "codexbar_command", "codexbar_url", "codexbar_source", "codexbar_provider"}
    for account in data.get("accounts", []):
        if set(account) - allowed:
            raise ValueError("Only credential-free account metadata is allowed")
        if account.get("provider") == "gemini":  # one Google pet now, Anti; an old Gemini account still reads Gemini
            account["provider"] = "antigravity"
            account.setdefault("codexbar_provider", "gemini")
        if account.get("provider") not in ("claude", "codex", "grok", "copilot", "antigravity"):
            raise ValueError("Unknown provider")
        if account["provider"] in CODEXBAR_ONLY and not (uses_codexbar(account) or account.get("snapshot_file")):
            raise ValueError(f"{account['provider'].title()} is read through CodexBar: set codexbar_command or codexbar_url")
        check_codexbar(account)
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


def uses_codexbar(account):
    return bool(account.get("codexbar_command") or account.get("codexbar_url"))


def check_codexbar(account):
    """CodexBar input is either its CLI or a `codexbar serve` /usage URL, for providers checked against it."""
    fields = {"codexbar_command", "codexbar_url", "codexbar_source"} & set(account)
    if not fields:
        return
    command, url = account.get("codexbar_command"), account.get("codexbar_url")
    if account["provider"] not in ("claude", "codex", "copilot", "antigravity"):
        raise ValueError("CodexBar input is checked for claude, codex, copilot and antigravity accounts only")
    if account.get("codexbar_provider") and (account["provider"] != "antigravity"
                                             or account["codexbar_provider"] not in ("gemini", "antigravity")):
        raise ValueError("codexbar_provider picks antigravity or gemini for an Antigravity account")
    if bool(command) == bool(url) or account.get("snapshot_file"):
        raise ValueError("Use one of codexbar_command or codexbar_url, without snapshot_file")
    if command is not None and not (isinstance(command, str) and command.strip()):
        raise ValueError("codexbar_command must be a command or path")
    if url is not None:
        parts = urlparse(url) if isinstance(url, str) else None
        # Credential-free: no user:password@, and no query other than CodexBar's provider filter.
        if (not parts or parts.scheme not in ("http", "https") or not parts.hostname or "@" in parts.netloc
                or parts.fragment or set(parse_qs(parts.query, keep_blank_values=True)) - {"provider"}):
            raise ValueError("codexbar_url must be an http(s) /usage address without credentials")
    if "codexbar_source" in account and (url or account["codexbar_source"] not in CODEXBAR_SOURCES):
        raise ValueError("codexbar_source is one of " + ", ".join(sorted(CODEXBAR_SOURCES)) + " and only for codexbar_command")


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
        subprocess.run([exe("claude"), "-p", "Reply only OK.", "--tools", "",
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
    rpc = RPC([exe("codex"), "app-server"], env)
    try:
        rpc.call("initialize", {"clientInfo": {"name": "token_tv", "title": "TokenTV", "version": __version__}, "capabilities": {}})
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
    rpc = RPC([exe(command), "agent", "--no-leader", "stdio"], env)
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


# Services TokenTV reads only through CodexBar, which owns their logins. An Antigravity account reads CodexBar's
# antigravity entry, or its gemini one with `codexbar_provider` (CodexBar reads Gemini's quota through Antigravity).
CODEXBAR_ONLY = ("copilot", "antigravity")


def codexbar_name(account):
    return account.get("codexbar_provider") or account["provider"]


def codexbar_payload(account):
    """CodexBar's usage JSON. CodexBar owns the login; TokenTV only reads what it prints or serves."""
    if account.get("codexbar_url"):
        return json_get(account["codexbar_url"])
    command = [exe(os.path.expanduser(account["codexbar_command"])), "usage",
               "--provider", codexbar_name(account), "--format", "json"]
    if account.get("codexbar_source"):
        command += ["--source", account["codexbar_source"]]
    env = (scoped_env(account["provider"], Path(account["source_home"]).expanduser())
           if account.get("source_home") and account["provider"] not in CODEXBAR_ONLY else None)
    try:
        result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, timeout=60)
    except FileNotFoundError:
        raise SourceError("cli_unavailable") from None
    try:
        # A failed provider still prints its JSON error entry, with a non-zero exit.
        return json.loads(result.stdout)
    except ValueError:
        raise SourceError("invalid_codexbar_output") from None


def codexbar_emails(entry):
    """Account emails CodexBar reported for this entry (its `account` label is a display name, not one)."""
    usage = entry.get("usage") if isinstance(entry.get("usage"), dict) else {}
    identity = usage.get("identity") if isinstance(usage.get("identity"), dict) else {}
    return [value for value in (identity.get("accountEmail"), usage.get("accountEmail"))
            if isinstance(value, str) and value.strip()]


def codexbar_entry(data, account):
    """This account's entry and whether CodexBar reported its email. Every reported email must match."""
    if not isinstance(data, list):
        raise SourceError("invalid_codexbar_output")
    entries = [entry for entry in data if isinstance(entry, dict) and entry.get("provider") == codexbar_name(account)]
    if not entries:
        raise SourceError("codexbar_provider_missing")
    for entry in entries:
        emails = codexbar_emails(entry)
        if emails and all(identity_matches(account["email"], email) for email in emails):
            return entry, True
    if len(entries) == 1 and not codexbar_emails(entries[0]):
        return entries[0], False
    raise SourceError("identity_mismatch")


def codexbar_error(error):
    """An error code only; CodexBar's message text is never kept."""
    message = str(error.get("message", "")).lower() if isinstance(error, dict) else ""
    if any(word in message for word in AUTH_WORDS):
        return "auth_required"
    kind = error.get("kind") if isinstance(error, dict) else None
    return "codexbar_" + kind if kind in ("args", "config", "provider", "runtime") else "codexbar_error"


def logged_in_email(provider, home, why=None):
    """The email of the account already signed in to this CLI home, or None; then, when `why` is a list, the reason
    goes into it: 'refused' (expired or revoked), 'busy', 'offline', 'not_chatgpt' or 'unreadable'. Prints nothing
    secret."""
    root = Path(home).expanduser()
    try:
        if provider == "claude":
            headers = {"Authorization": "Bearer " + claude_token(root), "Accept": "application/json",
                       "User-Agent": "claude-code/2.1.287", "anthropic-beta": "oauth-2025-04-20"}
            return email_from_profile(json_get("https://api.anthropic.com/api/oauth/profile", headers))
        if provider == "codex":
            if not (root / "auth.json").is_file():
                return None
            rpc = RPC([exe("codex"), "app-server"], scoped_env("codex", root))
            try:
                rpc.call("initialize", {"clientInfo": {"name": "token_tv", "title": "TokenTV", "version": __version__},
                                        "capabilities": {}})
                rpc.process.stdin.write('{"method":"initialized","params":{}}\n')
                rpc.process.stdin.flush()
                identity = rpc.call("account/read", {"refreshToken": True}).get("account") or {}
                if identity.get("type") != "chatgpt" and why is not None:
                    why.append("not_chatgpt")
                return identity.get("email") if identity.get("type") == "chatgpt" else None
            finally:
                rpc.close()
        return grok_identity({"source_home": str(root)})
    except (SourceError, OSError, ValueError, KeyError, TypeError, HTTPError, subprocess.SubprocessError) as error:
        if why is not None:
            code = getattr(error, "code", None)
            why.append("refused" if code in (401, 403) else "busy" if code == 429 else
                       "offline" if isinstance(error, OSError) and not isinstance(error, HTTPError) else "unreadable")
        return None


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
    provider = "antigravity" if row.get("provider") == "gemini" else row.get("provider")  # from before Anti
    if provider != account["provider"] or row.get("alias") != account["alias"]:
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
        if str(value.get("label", "")).rstrip("2") not in {"5H", "WEEK", "WINDOW", "BUDGET", "MONTH", "CHAT", "DAY"}:
            continue
        item = window(value["label"], value.get("used_percent"), value.get("resets_at"),
                      value.get("duration_minutes"))
        if item:
            clean["windows"].append(item)
    credits = row.get("reset_credits")  # saved limit resets come across too
    if isinstance(credits, dict) and isinstance(credits.get("count"), int) and not isinstance(credits["count"], bool):
        clean["reset_credits"] = {"count": max(0, credits["count"]), "expires_at": timestamp(credits.get("expires_at"))}
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
        if uses_codexbar(account):
            row["source"] = "codexbar"
            entry, verified = codexbar_entry(codexbar_payload(account), account)
            if entry.get("error"):
                raise SourceError(codexbar_error(entry["error"]))
            if not isinstance(entry.get("usage"), dict):
                raise SourceError("invalid_codexbar_output")
            row["windows"] = normalize_codexbar(entry)
            row["identity_verified"] = verified
        elif account["provider"] == "claude":
            profile, data = claude_payload(account)
            if not identity_matches(account["email"], email_from_profile(profile)):
                raise SourceError("identity_mismatch")
            row["windows"] = normalize_claude(data)
            row["identity_verified"] = True
        elif account["provider"] == "codex":
            data = codex_payload(account)
            row["windows"] = normalize_codex(data)
            credits = reset_credits(data)
            if credits:
                row["reset_credits"] = credits
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
