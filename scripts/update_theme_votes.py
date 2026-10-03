"""Refresh token_tv/assets/theme-votes.json by hand before a release.

Counts only the 👍 on each theme issue's body (not comments, not other reactions), through the
anonymous public GitHub REST API. A failed lookup keeps the last count and marks it stale; a theme
that was never counted stays unknown. Nothing is posted and no token is used.

    python3 scripts/update_theme_votes.py            # write the snapshot
    python3 scripts/update_theme_votes.py --dry-run  # print it
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from token_tv.catalog import CATALOG_PATH, REPO, VOTES_PATH, load_catalog, load_votes  # noqa: E402


def thumbs_up(payload):
    reactions = payload.get('reactions') if isinstance(payload, dict) else None
    count = reactions.get('+1') if isinstance(reactions, dict) else None
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError('No 👍 count in the response')
    return count


def github_fetch(issue, repo=REPO):
    request = Request(f'https://api.github.com/repos/{repo}/issues/{int(issue)}',
                      headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'token-tv-vote-refresh'})
    with urlopen(request, timeout=15) as response:
        return thumbs_up(json.load(response))


def refresh(catalog, votes, fetch, now):
    """Fresh counts get `now`; a failed issue keeps its old count *and* its old time, marked stale."""
    counts = {k: dict(v) for k, v in votes.get('counts', {}).items()}
    for theme in catalog['themes']:
        issue = theme['like_issue']
        if not issue:
            continue
        try:
            counts[str(issue)] = {'count': fetch(issue), 'status': 'fresh', 'fetched_at': now}
        except (OSError, ValueError) as error:
            print(f'{theme["id"]}: issue #{issue} not counted ({type(error).__name__}); keeping the last value',
                  file=sys.stderr)
            if str(issue) in counts:
                counts[str(issue)]['status'] = 'stale'
    return {'schema_version': 1, 'last_attempt_at': now, 'counts': counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    out = refresh(load_catalog(CATALOG_PATH), load_votes(VOTES_PATH), github_fetch, now)
    text = json.dumps(out, indent=2) + '\n'
    if args.dry_run:
        print(text, end='')
        return
    temp = VOTES_PATH.with_suffix('.tmp')
    temp.write_text(text)
    temp.replace(VOTES_PATH)
    print(f'Wrote {VOTES_PATH} ({sum(v["status"] == "fresh" for v in out["counts"].values())} counted now, attempt at {out["last_attempt_at"]})')


if __name__ == '__main__':
    main()
