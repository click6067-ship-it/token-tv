#!/usr/bin/env node
// One-line launcher: `npx token-tv start`.
// Runs the Python package in this folder: with uv if it is on PATH; else with a Python 3.10+ in a private venv; else
// with a private uv, one pinned release fetched once from Astral's GitHub releases and checked against the SHA-256
// kept below, which brings its own Python. Node is the only thing to have installed.
const { spawnSync } = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const args = process.argv.slice(2);
const win = process.platform === 'win32';
const cache = path.join(win ? (process.env.LOCALAPPDATA || os.homedir())
  : (process.env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache')), 'token-tv');
const env = { ...process.env, TOKEN_TV_LAUNCHER: 'npx' };  // so TokenTV tells you `npx token-tv ...` commands
const run = (cmd, argv) => {
  const r = spawnSync(cmd, argv, { stdio: 'inherit', env });
  return r.status === null ? 1 : r.status;
};
const which = (cmd) => {
  const r = spawnSync(win ? 'where' : 'which', [cmd], { encoding: 'utf8' });
  return r.status === 0 ? r.stdout.split(/\r?\n/)[0].trim() : null;
};
const fail = (text) => { console.error(text); process.exit(1); };
const version = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).version;

// pip and uv build a package in its own folder and leave build files there; npm's folder may not be writable (a
// global install), so they get a copy of this release in the cache, made once.
function source() {
  const dir = path.join(cache, `python-${version}-${crypto.createHash('sha256').update(root).digest('hex').slice(0, 8)}`);
  if (!fs.existsSync(dir)) {
    const part = `${dir}.${process.pid}`;
    try {
      fs.cpSync(root, part, { recursive: true, filter: (from) => !['node_modules', 'build'].includes(path.basename(from)) });
      writable(part);  // a read-only install (a Nix store, say) copies read-only, and nothing could build in it
      fs.renameSync(part, dir);
    } catch {  // another run made it meanwhile, or no room: then the npm folder as it is
      fs.rmSync(part, { recursive: true, force: true });
      return fs.existsSync(dir) ? dir : root;
    }
  }
  return dir;
}

function writable(at) {
  const stat = fs.statSync(at);
  fs.chmodSync(at, stat.mode | 0o200);
  if (stat.isDirectory()) for (const name of fs.readdirSync(at)) writable(path.join(at, name));
}


// A private venv for this release, made again from scratch when the release or the Python changed. False when this
// Python cannot make one (Debian's python3 without python3-venv, say): then the private uv below does it.
function preparedVenv(py) {
  const venv = path.join(cache, 'venv');
  const bin = path.join(venv, win ? 'Scripts' : 'bin');
  const stamp = path.join(venv, '.token-tv-source');
  const made = `${root}@${version}@${py}`;
  if (fs.existsSync(stamp) && fs.readFileSync(stamp, 'utf8') === made) return true;
  console.error('First run: preparing TokenTV (about a minute)...');
  const quiet = (cmd, argv) => spawnSync(cmd, argv, { stdio: ['ignore', 'ignore', 'inherit'], env }).status === 0;
  if (!quiet(py, ['-m', 'venv', '--clear', venv]) || !quiet(path.join(bin, 'python'), ['-m', 'pip', 'install', '-q', source()])) {
    fs.rmSync(venv, { recursive: true, force: true });
    return false;
  }
  fs.writeFileSync(stamp, made);
  return true;
}

// No usable Python: a private uv, which fetches a Python of its own. One release, pinned: the same TokenTV always
// bootstraps the same uv, and its bytes are checked against the digests here, read from that release's .sha256 files
// when it was pinned (and the Linux x86-64 archive hashed again), not against a checksum fetched with the download.
const UV_VERSION = '0.13.6';
const TARGETS = {
  'linux-x64': 'x86_64-unknown-linux-gnu', 'linux-arm64': 'aarch64-unknown-linux-gnu',
  'darwin-x64': 'x86_64-apple-darwin', 'darwin-arm64': 'aarch64-apple-darwin',
  'win32-x64': 'x86_64-pc-windows-msvc', 'win32-arm64': 'aarch64-pc-windows-msvc',
};
const UV_SHA256 = {
  'x86_64-unknown-linux-gnu': 'f29c3e94ffabd7e6f3ba521dba169a9b7ec12100bf3257087f0f24f6123f3645',
  'aarch64-unknown-linux-gnu': '229e194255c7958d86d56e8790d969a6f74736592133f0dfd0076f754c642c1d',
  'x86_64-apple-darwin': '63ba17fdda55ad1a230d4b37fc6017ffa10c23688c83818bd3bfdf914c652a02',
  'aarch64-apple-darwin': '60fbd5c8a1ed681845eea28d9d622fcde03c51e91a43465b64a1e17db1ed3472',
  'x86_64-pc-windows-msvc': 'a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f',
  'aarch64-pc-windows-msvc': 'c2426c0c8e28b53d8c440e47a18d96ad4db51e159866c0e81435b196d7f0081c',
};

// The pinned uv archive for a platform and CPU (as Node names them): {target, name, url}, or null where uv has no build.
function uvAsset(platform, arch) {
  const target = TARGETS[`${platform}-${arch}`];
  if (!target) return null;
  const name = `uv-${target}.${platform === 'win32' ? 'zip' : 'tar.gz'}`;
  return { target, name, url: `https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${name}` };
}

// Whether these bytes are the pinned release's archive for `target`.
function checkUv(archive, target) {
  const expected = UV_SHA256[target];
  return Boolean(expected) && crypto.createHash('sha256').update(archive).digest('hex') === expected;
}

async function download(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} for ${url}`);
  return Buffer.from(await response.arrayBuffer());
}

async function privateUvx(python) {
  const dir = path.join(cache, `uv-${UV_VERSION}`);  // a uv an older launcher fetched is not reused
  const exe = path.join(dir, win ? 'uvx.exe' : 'uvx');
  if (fs.existsSync(exe)) return exe;
  const asset = uvAsset(process.platform, process.arch);
  if (!asset) fail('TokenTV needs Python 3.10 or newer on this computer: https://www.python.org/downloads/');
  const { name, url, target } = asset;
  console.error(python ? `First run: TokenTV could not prepare itself with ${python}, so it fetches uv ${UV_VERSION}, which brings its own Python (about a minute)...`
    : `First run: no Python 3.10+ here, so TokenTV fetches uv ${UV_VERSION}, which brings its own (about a minute)...`);
  let archive;
  try {
    archive = await download(url);
  } catch (error) {
    fail(`Could not download uv (${error.message}). Install Python 3.10+ or uv (https://docs.astral.sh/uv/) and run this again.`);
  }
  if (!checkUv(archive, target)) {
    fail(`The uv download did not match the checksum TokenTV keeps for uv ${UV_VERSION}; nothing was installed. Try again later.`);
  }
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, name);
  fs.writeFileSync(file, archive);
  // tar comes with macOS, Linux and Windows 10+, and reads zip files too.
  const unpacked = run('tar', ['-xf', file, '-C', dir, ...(win ? [] : ['--strip-components', '1'])]);
  fs.rmSync(file, { force: true });
  if (unpacked || !fs.existsSync(exe)) fail('Could not unpack uv. Install uv (https://docs.astral.sh/uv/) and run this again.');
  return exe;
}

function main() {
  const uvx = which('uvx');
  if (uvx) process.exit(run(uvx, ['--from', source(), 'token-tv', ...args]));

  // A Python new enough (macOS ships 3.9; Windows may have only the Microsoft Store's python stub, which fails here).
  const python = ['python3', 'python', 'py'].map(which)
    .find((p) => p && spawnSync(p, ['-c', 'import sys; sys.exit(sys.version_info < (3, 10))']).status === 0);
  if (python && preparedVenv(python)) process.exit(run(path.join(cache, 'venv', win ? 'Scripts' : 'bin', 'token-tv'), args));

  privateUvx(python).then((exe) => {
    env.TOKEN_TV_UVX = exe;  // so starting with the computer can use the same uv
    process.exit(run(exe, ['--from', source(), 'token-tv', ...args]));
  });
}

if (require.main === module) main();
module.exports = { UV_VERSION, TARGETS, UV_SHA256, uvAsset, checkUv };
