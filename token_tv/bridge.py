"""Transfer normalized usage only; credentials stay on the source computer."""
import argparse
import json
import shlex
import subprocess
import time

from token_tv.sources import load_config
from token_tv.state import UsageStore

REMOTE_WRITE = """import json,os,pathlib,sys
p=pathlib.Path(sys.argv[1]).expanduser()
data=json.load(sys.stdin)
p.parent.mkdir(parents=True,exist_ok=True)
t=p.with_suffix('.tmp')
t.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')))
os.chmod(t,0o600)
t.replace(p)
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--remote-path", required=True)
    args = parser.parse_args()
    if args.ssh_host.startswith("-"):
        parser.error("A host name is required")
    config = load_config(args.config)
    store = UsageStore(config["accounts"])
    while True:
        try:
            store.refresh()
            data = json.dumps(store.snapshot(), ensure_ascii=False, separators=(",", ":"))
            command = "python3 -c " + shlex.quote(REMOTE_WRITE) + " " + shlex.quote(args.remote_path)
            subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                            args.ssh_host, command], input=data, text=True, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            print("TokenTV normalized account snapshot delivered.", flush=True)
        except (OSError, subprocess.SubprocessError):
            print("TokenTV bridge unavailable; display will mark stale.", flush=True)
        time.sleep(max(60, int(config.get("poll_seconds", 300))))


if __name__ == "__main__":
    main()
