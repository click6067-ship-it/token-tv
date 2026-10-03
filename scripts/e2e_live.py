"""Check the running dashboard without opening credential files."""
import argparse
import json
from pathlib import Path
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18787")
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--expect", type=int, help="number of configured accounts")
    parser.add_argument("--output")
    args = parser.parse_args()
    with urlopen(args.url.rstrip("/") + "/snapshot", timeout=15) as response:
        payload = response.read()
        status = response.status
    snapshot = json.loads(payload)
    assert snapshot["schema"] == 1
    assert snapshot["accounts"], "no accounts reported"
    if args.expect is not None:
        assert len(snapshot["accounts"]) == args.expect, f"expected {args.expect} accounts"
    connected = []
    pending = []
    for key, row in snapshot["accounts"].items():
        assert not set(row) & {"email", "password", "access_token", "refresh_token", "source_home"}
        if row["status"] in ("ok", "quota_unavailable") and row["identity_verified"] is True:
            connected.append(key)
        else:
            pending.append(key)
    result = {"http_status": status, "connected": sorted(connected), "pending": sorted(pending),
              "quota_unavailable": sorted(k for k, row in snapshot["accounts"].items() if row["status"] == "quota_unavailable"),
              "expected": len(snapshot["accounts"]), "all_authenticated": not pending, "updated_at": snapshot["updated_at"]}
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    if args.require_all and pending:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
