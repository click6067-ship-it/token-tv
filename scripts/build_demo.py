"""Build the static TokenTV web demo: sample accounts and pre-rendered clock faces.

The output is plain files for any static host (the live demo runs on Vercel):
    python3 scripts/build_demo.py --out site --site-url https://example.com
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from token_tv.display import STYLES, render_page  # noqa: E402
from token_tv.web_assets import ASSETS, WEB  # noqa: E402
from token_tv.sample import snapshot  # noqa: E402
from token_tv.catalog import payload as theme_payload  # noqa: E402

REPO = 'https://github.com/click6067-ship-it/token-tv'
META = '''<meta name="description" content="Your AI limits, on a tiny desk clock. Claude and Codex usage, several accounts, no firmware flashing. Grok CLI budget is experimental.">
<meta property="og:title" content="TokenTV · Live demo">
<meta property="og:description" content="Your AI limits, on a tiny desk clock. Claude and Codex · multiple accounts · no flashing.">
<meta property="og:image" content="{site}/og.png">
<meta property="og:url" content="{site}/">
<meta name="twitter:card" content="summary_large_image">'''
BAR = f'<div class="demo-bar">Live demo with sample data<a href="{REPO}">TokenTV on GitHub</a></div>'


def build(out, site):
    out.mkdir(parents=True, exist_ok=True)
    for child in out.iterdir():  # keep the host's project link (.vercel)
        if child.name != '.vercel':
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    html = (WEB / 'index.html').read_text()
    html = html.replace('<html lang="en" data-theme="digital">', '<html lang="en" data-theme="digital" data-demo>', 1)
    html = html.replace('<title>TokenTV · AI usage</title>', '<title>TokenTV · Live demo</title>\n' + META.format(site=site.rstrip('/')), 1)
    html = html.replace('<a class="skip" href="#providers">Skip to usage</a>', '<a class="skip" href="#providers">Skip to usage</a>\n' + BAR, 1)
    assert 'data-demo' in html and 'demo-bar' in html and 'og:image' in html, 'index.html markers changed'
    (out / 'index.html').write_text(html)
    assets = out / 'assets'
    assets.mkdir()
    for path, (file, _) in ASSETS.items():
        shutil.copy2(file, assets / path.rsplit('/', 1)[1])
    for notice in WEB.glob('*-LICENSE.txt'):
        shutil.copy2(notice, assets / notice.name)
    (out / 'demo-snapshot.json').write_text(json.dumps(snapshot(), separators=(',', ':')))
    frames = out / 'frames'
    frames.mkdir()
    rendered = snapshot(time.time())
    paths = {}
    for style in STYLES:
        image = render_page(rendered, style=style)
        name = f"{style}.{'gif' if image[:4] == b'GIF8' else 'jpg'}"  # Space is animated
        (frames / name).write_bytes(image)
        paths[style] = f'/frames/{name}'
    display = {'style': 'digital', 'applied_style': 'digital', 'status': 'preview_only', 'styles': list(STYLES), 'frames': paths}
    (out / 'demo-display.json').write_text(json.dumps(display))
    (out / 'demo-themes.json').write_text(json.dumps(theme_payload()))
    shutil.copy2(ROOT / 'docs' / 'images' / 'social-preview.png', out / 'og.png')
    return sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and '.vercel' not in p.parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', default='site')
    parser.add_argument('--site-url', default='https://token-tv.vercel.app', help='absolute URL for link previews')
    args = parser.parse_args()
    files = build(Path(args.out), args.site_url)
    print(f'{len(files)} files in {args.out}')


if __name__ == '__main__':
    main()
