"""Synthetic accounts for the demo, the sample renders and tests. No real account data."""
H, D = 3600, 86400
# key, alias, provider, [(window, used %, seconds until reset)]
SAMPLE = [
    ('claude_a', 'CLAUDE A', 'claude', [('WEEK', 86, 3 * D), ('5H', 41, 2 * H)]),
    ('claude_b', 'CLAUDE B', 'claude', [('5H', 52, 3 * H + 41 * 60), ('WEEK', 30, 5 * D)]),
    ('claude_c', 'CLAUDE C', 'claude', [('5H', 97, 38 * 60), ('WEEK', 64, 4 * D)]),
    ('codex_a', 'CODEX A', 'codex', [('5H', 34, 2 * H + 12 * 60)]),
    ('codex_b', 'CODEX B', 'codex', [('WEEK', 91, D + 4 * H)]),
    ('grok_a', 'GROK A', 'grok', [('BUDGET', 61, 6 * D + 2 * H)]),
    ('grok_b', 'GROK B', 'grok', [('BUDGET', 18, 12 * D + 3 * H)]),
]


def snapshot(now=None, sample=SAMPLE):
    accounts = {}
    for key, alias, provider, windows in sample:
        row = {'key': key, 'alias': alias, 'provider': provider, 'status': 'ok', 'identity_verified': True,
               'windows': [{'label': label, 'used_percent': used, 'resets_in': reset} for label, used, reset in windows]}
        if now is not None:
            row['fetched_at'] = row['last_success_at'] = now
            for window in row['windows']:
                window['resets_at'] = now + window['resets_in']
        accounts[key] = row
    return {'schema': 1, 'updated_at': now or 0, 'accounts': accounts}
