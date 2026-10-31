"""The npm launcher's no-Python path: one pinned uv release, checked against digests kept in the launcher, never
against a checksum fetched from the same moving release. Offline: downloads are stand-ins."""
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # helpers.py, however the tests are run
from helpers import temp_dir

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'bin' / 'token-tv.js'
NODE = shutil.which('node')


def node(script):
    done = subprocess.run([NODE, '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=60)
    if done.returncode:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


@unittest.skipUnless(NODE, 'needs Node')
class PinnedUvTests(unittest.TestCase):
    def test_every_platform_has_a_pinned_release_and_digest(self):
        found = node("const l = require('./bin/token-tv.js'); console.log(JSON.stringify({version: l.UV_VERSION, "
                     "targets: l.TARGETS, sums: l.UV_SHA256, assets: Object.keys(l.TARGETS).map((k) => l.uvAsset(...k.split('-')))}))")
        self.assertRegex(found['version'], r'^\d+\.\d+\.\d+$')
        self.assertEqual(len(found['assets']), 6)
        for asset in found['assets']:
            self.assertRegex(found['sums'][asset['target']], r'^[0-9a-f]{64}$', asset)
            self.assertEqual(asset['url'], f"https://github.com/astral-sh/uv/releases/download/{found['version']}/{asset['name']}")
        source = LAUNCHER.read_text(encoding='utf-8')
        self.assertNotIn('releases/latest', source)
        self.assertNotIn('.sha256`', source)  # no checksum fetched beside the download

    def test_only_the_pinned_bytes_pass(self):
        found = node("const l = require('./bin/token-tv.js'); const t = l.TARGETS['linux-x64']; const fake = Buffer.from('not uv');"
                     "const before = l.checkUv(fake, t); l.UV_SHA256[t] = require('node:crypto').createHash('sha256').update(fake).digest('hex');"
                     "console.log(JSON.stringify({wrong: before, right: l.checkUv(fake, t), unknown: l.checkUv(fake, 'no-such-target')}))")
        self.assertEqual(found, {'wrong': False, 'right': True, 'unknown': False})

    @unittest.skipIf(sys.platform == 'win32', 'PATH without Python is set up the POSIX way here; CI covers Windows')
    def test_with_no_python_a_wrong_download_stops_before_anything_is_unpacked(self):
        folder = temp_dir(self)
        only = folder / 'bin'
        only.mkdir()
        os.symlink(NODE, only / 'node')  # Node and nothing else: no python3, python, py, uvx, which or tar
        fetched = folder / 'fetched.txt'
        stub = folder / 'stub.js'
        stub.write_text("const fs = require('node:fs');\n"
                        f"globalThis.fetch = async (url) => {{ fs.appendFileSync({json.dumps(str(fetched))}, url + '\\n');"
                        " return new Response(Buffer.from('not the uv release')); };\n", encoding='utf-8')
        env = {'PATH': str(only), 'HOME': str(folder), 'XDG_CACHE_HOME': str(folder / 'cache')}
        done = subprocess.run([str(only / 'node'), '--require', str(stub), str(LAUNCHER), '--version'], env=env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn('did not match', done.stderr)
        urls = fetched.read_text(encoding='utf-8').split()
        version = node("console.log(JSON.stringify(require('./bin/token-tv.js').UV_VERSION))")
        self.assertEqual(len(urls), 1)  # the archive only: no checksum file from the same release
        self.assertIn(f'/releases/download/{version}/uv-', urls[0])
        uv = folder / 'cache' / 'token-tv'
        self.assertFalse(any(p.name.startswith('uv') for p in uv.iterdir()) if uv.exists() else False)  # nothing kept


class CiTests(unittest.TestCase):
    def test_ci_runs_the_launcher_where_no_python_can_be_found(self):
        workflow = (ROOT / '.github' / 'workflows' / 'test.yml').read_text(encoding='utf-8')
        job = workflow.split('no-python:', 1)[1]
        self.assertIn('bin/token-tv.js', job)
        self.assertIn('command -v python3', job)  # it proves there is none before it runs
        self.assertIn('token-tv/uv-', job)  # and that the pinned uv was fetched


if __name__ == '__main__':
    unittest.main()
