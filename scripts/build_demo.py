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
COLLECTION_ENTRY = '''<section class="demo-collection" aria-labelledby="demo-collection-title">
    <div><p class="eyebrow">AI desk pets</p><h2 id="demo-collection-title">Your AI has moods.</h2>
    <p>Everyday reactions. Rare finds. Unique and Legend scenes to discover.</p></div>
    <a class="control primary" href="/collection/">Animation Collection →</a>
  </section>
  '''
COLLECTION_STYLE = '''<style id="collection-entry-style">
/* Hallmark · component: collection entry · existing dashboard tokens
   Pre-emit critique: P4 H5 E4 S5 R5 V4 */
.demo-collection{display:flex;align-items:center;justify-content:space-between;gap:20px;margin:18px 0;padding:22px;border:1px solid var(--line-2);border-left:4px solid var(--codex);border-radius:var(--radius-control);background:var(--panel);color:var(--ink)}
.demo-collection h2{font:700 25px/1.2 var(--font-label);font-style:normal;letter-spacing:0;margin:5px 0 8px;overflow-wrap:anywhere;min-width:0}
.demo-collection p:last-child{margin:0;color:var(--ink-2);font:400 14px/1.5 var(--font-body)}
.demo-collection .primary{display:inline-flex;justify-content:center;align-items:center;flex-shrink:0;min-height:48px;padding:12px 20px;text-decoration:none;white-space:nowrap;font:700 16px/1.3 var(--font-label)}
.demo-collection .primary:active{transform:translateY(1px)}
@media(max-width:700px){.demo-collection{align-items:stretch;flex-direction:column;gap:16px;padding:18px}.demo-collection .primary{width:100%;font-size:15px}}
</style>'''


def add_collection_entry(html):
    """Keep the public animation catalogue one click away, above the demo controls."""
    if 'id="demo-collection-title"' in html:
        return html
    marker = '<nav class="theme-section"'
    assert marker in html and '</head>' in html, 'public demo navigation markers changed'
    return html.replace('</head>', COLLECTION_STYLE + '\n</head>', 1).replace(marker, COLLECTION_ENTRY + marker, 1)


def build(out, site):
    out.mkdir(parents=True, exist_ok=True)
    for child in out.iterdir():  # keep the host's project link (.vercel)
        if child.name != '.vercel':
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    html = (WEB / 'index.html').read_text(encoding='utf-8')
    html = html.replace('<html lang="en" data-theme="digital">', '<html lang="en" data-theme="digital" data-demo>', 1)
    html = html.replace('<title>TokenTV · AI usage</title>', '<title>TokenTV · Live demo</title>\n' + META.format(site=site.rstrip('/')), 1)
    html = html.replace('<a class="skip" href="#providers">Skip to usage</a>', '<a class="skip" href="#providers">Skip to usage</a>\n' + BAR, 1)
    html = add_collection_entry(html)
    assert 'data-demo' in html and 'demo-bar' in html and 'og:image' in html, 'index.html markers changed'
    (out / 'index.html').write_text(html, encoding='utf-8')
    assets = out / 'assets'
    assets.mkdir()
    for path, (file, _) in ASSETS.items():
        shutil.copy2(file, assets / path.rsplit('/', 1)[1])
    for notice in WEB.glob('*-LICENSE.txt'):
        shutil.copy2(notice, assets / notice.name)
    (out / 'demo-snapshot.json').write_text(json.dumps(snapshot(), separators=(',', ':')), encoding='utf-8')
    frames = out / 'frames'
    frames.mkdir()
    rendered = snapshot(time.time())
    paths = {}
    for style in STYLES:
        image = render_page(rendered, style=style)
        name = f"{style}.{'gif' if image[:4] == b'GIF8' else 'jpg'}"  # Space is animated
        (frames / name).write_bytes(image)
        paths[style] = f'/frames/{name}'
    display = {'style': 'arcade', 'applied_style': 'arcade', 'status': 'preview_only', 'styles': list(STYLES), 'frames': paths}
    (out / 'demo-display.json').write_text(json.dumps(display), encoding='utf-8')
    (out / 'demo-themes.json').write_text(json.dumps(theme_payload()), encoding='utf-8')
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
