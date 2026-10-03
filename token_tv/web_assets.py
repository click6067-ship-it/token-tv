"""Explicitly allowlisted web resources; never expose runtime files."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'web'
HTML = (WEB / 'index.html').read_text()
ASSETS = {
    '/assets/style.css': (WEB / 'style.css', 'text/css; charset=utf-8'),
    '/assets/app.js': (WEB / 'app.js', 'text/javascript; charset=utf-8'),
    '/assets/tokens.css': (ROOT.parent / 'tokens.css', 'text/css; charset=utf-8'),
    '/assets/manrope.ttf': (WEB / 'manrope.ttf', 'font/ttf'),
    '/assets/vt323.woff2': (WEB / 'vt323.woff2', 'font/woff2'),
    '/assets/dseg7-classic-bold.woff2': (WEB / 'dseg7-classic-bold.woff2', 'font/woff2'),
    '/assets/jersey-10.woff2': (WEB / 'jersey-10.woff2', 'font/woff2'),
    '/assets/orbitron.ttf': (WEB / 'orbitron.ttf', 'font/ttf'),
    '/assets/press-start-2p.ttf': (WEB / 'press-start-2p.ttf', 'font/ttf'),
    '/assets/oxanium.woff2': (WEB / 'oxanium.woff2', 'font/woff2'),
    '/assets/cormorant-garamond.woff2': (WEB / 'cormorant-garamond.woff2', 'font/woff2'),
    '/assets/chakra-petch-500.woff2': (WEB / 'chakra-petch-500.woff2', 'font/woff2'),
    '/assets/chakra-petch-700.woff2': (WEB / 'chakra-petch-700.woff2', 'font/woff2'),
    '/assets/claude-pixel.png': (ROOT / 'assets' / 'claude-pixel.png', 'image/png'),
    '/assets/codex-pixel.png': (ROOT / 'assets' / 'codex-pixel.png', 'image/png'),
    '/assets/grok-pixel.png': (ROOT / 'assets' / 'grok-pixel.png', 'image/png'),
}


def asset(path):
    entry = ASSETS.get(path)
    return (entry[0].read_bytes(), entry[1]) if entry else None
