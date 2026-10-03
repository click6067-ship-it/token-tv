#!/usr/bin/env node
// One-line launcher: `npx github:click6067-ship-it/token-tv demo`.
// Runs the Python package from this checkout with uv if present, otherwise with a private venv.
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const args = process.argv.slice(2);
const win = process.platform === 'win32';
const has = (cmd) => spawnSync(win ? 'where' : 'which', [cmd], { stdio: 'ignore' }).status === 0;
const run = (cmd, argv) => {
  const r = spawnSync(cmd, argv, { stdio: 'inherit', shell: win });
  return r.status === null ? 1 : r.status;
};

if (has('uvx')) process.exit(run('uvx', ['--from', root, 'token-tv', ...args]));

const python = ['python3', 'python', 'py'].find(has);
if (!python) {
  console.error('TokenTV needs Python 3.10 or newer: https://www.python.org/downloads/');
  process.exit(1);
}
const version = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).version;
const base = win ? (process.env.LOCALAPPDATA || os.homedir()) : (process.env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache'));
const venv = path.join(base, 'token-tv', 'venv');
const bin = path.join(venv, win ? 'Scripts' : 'bin');
const stamp = path.join(venv, '.token-tv-source');
const source = `${root}@${version}`;
if (!fs.existsSync(stamp) || fs.readFileSync(stamp, 'utf8') !== source) {
  console.error('First run: preparing TokenTV (about a minute)...');
  if (run(python, ['-m', 'venv', venv]) || run(path.join(bin, 'python'), ['-m', 'pip', 'install', '-q', root])) {
    console.error('Could not install TokenTV. Try: pip install git+https://github.com/click6067-ship-it/token-tv');
    process.exit(1);
  }
  fs.writeFileSync(stamp, source);
}
process.exit(run(path.join(bin, 'token-tv'), args));
