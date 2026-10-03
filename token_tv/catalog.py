"""Theme catalog: installed faces plus reviewed metadata and a manually refreshed likes snapshot.

Installed STYLES are the source of truth. The catalog only adds name/author/source/likes, so a face
you added in your own fork shows up as Local. Nothing here downloads or runs theme code.
"""
import json
import re
from datetime import datetime
from pathlib import Path

from token_tv import __version__
from token_tv.display import STYLES

ASSETS = Path(__file__).with_name('assets')
CATALOG_PATH = ASSETS / 'theme-catalog.json'
VOTES_PATH = ASSETS / 'theme-votes.json'
REPO = 'click6067-ship-it/token-tv'
BLANK_VOTES = {'schema_version': 1, 'last_attempt_at': None, 'counts': {}}
FIELDS = ('id', 'name', 'author', 'added_at', 'min_version', 'source_url', 'license', 'like_issue')


def version_tuple(text):
    parts = [int(p) for p in str(text).split('.')]
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def version_at_least(have, need):
    return version_tuple(have) >= version_tuple(need)


def validate_catalog(data):
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('themes'), list):
        raise ValueError('Unsupported theme catalog')
    seen = set()
    for theme in data['themes']:
        if not isinstance(theme, dict) or set(FIELDS) - set(theme):
            raise ValueError('Theme entries need ' + ', '.join(FIELDS))
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,31}', str(theme['id'])) or theme['id'] in seen:
            raise ValueError('Theme ids must be unique lowercase names')
        seen.add(theme['id'])
        issue = theme['like_issue']
        if issue is not None and (isinstance(issue, bool) or not isinstance(issue, int) or issue < 1):
            raise ValueError('like_issue must be an issue number or null')
        if not str(theme['source_url']).startswith('https://'):
            raise ValueError('source_url must be an https link')
        if theme.get('preview_url') is not None and not str(theme['preview_url']).startswith('https://'):
            raise ValueError('preview_url must be an https link')
        datetime.fromisoformat(str(theme['added_at']).replace('Z', '+00:00'))
        version_tuple(theme['min_version'])
    return data


def load_catalog(path=None):
    return validate_catalog(json.loads(Path(path or CATALOG_PATH).read_text()))


def parse_time(text):
    """A UTC timestamp string, or None when missing or unreadable."""
    try:
        return datetime.fromisoformat(str(text).replace('Z', '+00:00')).timestamp() if text else None
    except ValueError:
        return None


def load_votes(path=None):
    """The saved snapshot, or a blank one. Each count keeps the time it was really counted.

    A broken file, a bad count or an unreadable count time means unknown, never zero.
    """
    try:
        data = json.loads(Path(path or VOTES_PATH).read_text())
        counts = {}
        for issue, value in data['counts'].items():
            count, status, stamp = value.get('count'), value.get('status'), value.get('fetched_at')
            if isinstance(count, bool) or not isinstance(count, int) or count < 0 or status not in ('fresh', 'stale'):
                continue
            if stamp is not None and parse_time(stamp) is None:
                continue  # unreadable time: we cannot say when this number was true
            if status == 'fresh' and stamp is None:
                continue
            counts[str(issue)] = {'count': count, 'status': status, 'fetched_at': stamp}
        attempt = data.get('last_attempt_at')
        return {'schema_version': 1, 'last_attempt_at': attempt if parse_time(attempt) else None, 'counts': counts}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return dict(BLANK_VOTES)


def theme_list(installed=STYLES, catalog=None, votes=None, version=__version__, repo=REPO):
    catalog = load_catalog() if catalog is None else catalog
    votes = load_votes() if votes is None else votes
    known = {t['id']: t for t in catalog['themes']}
    themes = []
    for id in list(installed) + [i for i in known if i not in installed]:
        meta = known.get(id)
        if meta is None:
            themes.append({'id': id, 'name': id.replace('-', ' ').title(), 'author': None, 'local': True,
                           'installed': True, 'needs_update': False, 'min_version': None, 'added_at': None,
                           'source_url': None, 'license': None, 'preview_url': None,
                           'likes': None, 'likes_state': 'local', 'likes_counted_at': None, 'like_url': None})
            continue
        issue = meta['like_issue']
        count = votes['counts'].get(str(issue)) if issue else None
        state = 'not_open' if not issue else 'unavailable' if count is None else \
            'counted' if count['status'] == 'fresh' else 'stale'
        themes.append({'id': id, 'name': meta['name'], 'author': meta['author'], 'local': False,
                       'installed': id in installed,
                       'needs_update': id not in installed or not version_at_least(version, meta['min_version']),
                       'min_version': meta['min_version'], 'added_at': meta['added_at'],
                       'source_url': meta['source_url'], 'license': meta['license'],
                       'preview_url': meta.get('preview_url'),
                       'likes': count['count'] if count else None, 'likes_state': state,
                       'likes_counted_at': count['fetched_at'] if count else None,
                       'like_url': f'https://github.com/{repo}/issues/{issue}' if issue else None})
    return {'last_attempt_at': votes.get('last_attempt_at'), 'version': version, 'themes': sort_themes(themes, 'new')}


def _newest(theme):
    stamp = theme['added_at']
    return -datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp() if stamp else float('inf')


def sort_themes(themes, mode):
    """New: newest first, then id. Popular: known counts high to low, then the rest in New order."""
    new = sorted(themes, key=lambda t: (_newest(t), t['id']))
    if mode == 'new':
        return new
    counted = sorted((t for t in new if t['likes'] is not None), key=lambda t: -t['likes'])  # stable: keeps New order
    return counted + [t for t in new if t['likes'] is None]


def payload():
    """theme_list() for the dashboard; a broken catalog still lists every installed face as Local."""
    try:
        return theme_list()
    except (OSError, ValueError, KeyError, TypeError):
        return dict(theme_list(catalog={'schema_version': 1, 'themes': []}), catalog_error=True)
