'use strict';
/* TokenTV web dashboard. Every theme renders the same nodes; style.css composes them. */
const THEMES = [
 {id:'digital', name:'Digital Terminal', eyebrow:'', title:'AI USAGE DASHBOARD', note:''},
 {id:'neon', name:'Neon Cyberpunk', eyebrow:'Today', title:'AI USAGE', note:''},
 {id:'retro', name:'Pixel Retro', eyebrow:'', title:'AI PROVIDERS', note:'USAGE DASHBOARD'},
 {id:'modern', name:'Modern Minimal', eyebrow:'AI providers', title:'Usage Overview', note:'Track your usage and reset times across providers.'},
 {id:'sakura', name:'Sakura Blossom', eyebrow:'Dashboard', title:'AI Usage', note:'Three minds. More possibilities.'},
 {id:'hud', name:'Sci-Fi HUD', eyebrow:'', title:'AI PROVIDER USAGE', note:'Real-time usage monitor'}
];
const STATUS = {ok:'Connected', loading:'Loading', auth_required:'Login needed', identity_mismatch:'Check identity', quota_unavailable:'Quota unavailable', stale:'OLD · Previous value', rate_limited:'Retry later', error:'Fetch failed'};
const PROVIDERS = ['claude', 'codex', 'grok'];
const COMPANIES = {claude:'ANTHROPIC', codex:'OPENAI', grok:'XAI'};
const svgNS = 'http://www.w3.org/2000/svg';
const $ = s => document.querySelector(s);
const readPreference = (k, f) => {try {return JSON.parse(localStorage.getItem(k)) ?? f} catch {return f}};
const savePreference = (k, v) => {try {localStorage.setItem(k, JSON.stringify(v))} catch {/* Private browsing may disallow storage. */}};
let accountChoices = readPreference('tokentv.accounts', {});
if (!accountChoices || typeof accountChoices !== 'object' || Array.isArray(accountChoices)) accountChoices = {};
let snapshot = null, offline = false, polling = false, displayInfo = null, clockChoice = null, applying = false, clockError = false;
const el = (tag, text, cls) => {const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n};
function svgNode(tag, attrs) {const n = document.createElementNS(svgNS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n}
const clamp = v => Math.max(0, Math.min(100, v));
/* Unlit seven-segment cells behind Digital numerals: every glyph cell becomes 8. */
const ghost = text => text.replace(/[^\s:]/g, '8');
const pad = n => String(n).padStart(2, '0');
function seeded(seed) {return () => {seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296}}

/* Provider marks: vector glyphs for most themes, the project's pixel mascots for Pixel Retro. */
function icon(provider) {
 const s = svgNode('svg', {viewBox:'0 0 48 48', 'aria-hidden':'true', fill:'none', stroke:'currentColor', 'stroke-linecap':'round', 'stroke-linejoin':'round', class:'glyph'});
 if (provider === 'claude') {
  const reach = [19.5, 15, 18, 14, 19, 15.5, 18.5, 14, 19.5, 15, 18, 14.5];
  reach.forEach((r, i) => s.append(svgNode('path', {d:`M24 ${24 - 6} V${24 - r}`, 'stroke-width':3.4, transform:`rotate(${i * 30 + (i % 2 ? 4 : 0)} 24 24)`})));
 } else if (provider === 'codex') {
  s.append(svgNode('path', {d:'M24 5 40.5 14.5V33.5L24 43 7.5 33.5V14.5Z', 'stroke-width':3.2}));
  s.append(svgNode('path', {d:'M7.5 14.5 24 24 40.5 14.5M24 24V43', 'stroke-width':3.2}));
 } else {
  s.append(svgNode('circle', {cx:24, cy:24, r:12.5, 'stroke-width':3.4}));
  s.append(svgNode('path', {d:'M5 43C17 33 31 19 43 5 34 19 21 32 5 43Z', fill:'currentColor', stroke:'currentColor', 'stroke-width':1.6}));
 }
 return s;
}
function mascot(provider) {const img = el('img', undefined, 'pixel-mascot'); img.src = `/assets/${provider}-pixel.png`; img.alt = ''; img.width = 32; img.height = 32; img.decoding = 'async'; return img}
function clockGlyph() {
 const s = svgNode('svg', {viewBox:'0 0 24 24', 'aria-hidden':'true', fill:'none', stroke:'currentColor', 'stroke-width':1.8, 'stroke-linecap':'round', class:'clock-icon'});
 s.append(svgNode('circle', {cx:12, cy:12, r:9}), svgNode('path', {d:'M12 7.5V12l3 2'}));
 const p = svgNode('svg', {viewBox:'0 0 9 9', 'aria-hidden':'true', 'shape-rendering':'crispEdges', class:'clock-pixel'});
 for (const [x, y, w, h, c] of [[2,0,5,1,'o'],[1,1,1,1,'o'],[7,1,1,1,'o'],[0,2,1,5,'o'],[8,2,1,5,'o'],[1,7,1,1,'o'],[7,7,1,1,'o'],[2,8,5,1,'o'],[1,2,7,5,'f'],[2,1,5,1,'f'],[2,7,5,1,'f'],[4,2,1,3,'o'],[5,4,2,1,'o']])
  p.append(svgNode('rect', c === 'o' ? {x, y, width:w, height:h, fill:'currentColor'} : {x, y, width:w, height:h, fill:'#fff3d6', class:'face'}));
 const wrap = el('span', undefined, 'clock-mark'); wrap.setAttribute('aria-hidden', 'true'); wrap.append(s, p); return wrap;
}

/* Pixel Retro scenery on a 200×62 logical grid, anchored bottom-right. Sky objects sit
 * near x≈138 so they fall between the title row and the score column. */
function scene(provider) {
 const W = 200, H = 62, rnd = seeded({claude:11, codex:23, grok:37}[provider]);
 const s = svgNode('svg', {viewBox:`0 0 ${W} ${H}`, preserveAspectRatio:'xMaxYMax slice', 'shape-rendering':'crispEdges', class:'scene', 'aria-hidden':'true'});
 const rect = (x, y, w, h, fill, cls) => {const r = svgNode('rect', {x, y, width:w, height:h, fill}); if (cls) r.setAttribute('class', cls); s.append(r)};
 const bands = colors => colors.forEach((c, i) => rect(0, Math.floor(i * H / colors.length), W, Math.ceil(H / colors.length) + 1, c));
 const ridge = (f, fill) => {let d = `M0 ${H}`; for (let x = 0; x < W; x += 2) d += `V${Math.round(f(x))}H${x + 2}`; s.append(svgNode('path', {d:d + `V${H}Z`, fill}))};
 const disc = (cx, cy, r, fill) => {for (let dy = -r; dy <= r; dy++) {const w = Math.round(Math.sqrt(r * r - dy * dy)); rect(cx - w, cy + dy, 2 * w + 1, 1, fill)}};
 const pine = (x, base, h, fill) => {for (let i = 0; i < h; i++) {const w = 1 + 2 * Math.floor(i / 2); rect(x - Math.floor(w / 2), base - h + i, w, 1, fill)} rect(x, base, 1, 2, fill)};
 const stars = (n, x0, y1, colors) => {for (let i = 0; i < n; i++) rect(x0 + Math.floor(rnd() * (W - x0)), Math.floor(rnd() * y1), 1, 1, colors[i % colors.length], i % 3 ? '' : 'twinkle')};
 if (provider === 'claude') {
  bands(['#2a1330', '#3a1834', '#4d1f36', '#652836', '#7f3335', '#9a4133', '#b65231', '#cf6630']);
  disc(138, 15, 9, '#ff9e4f'); disc(138, 15, 7, '#ffc067'); disc(138, 14, 4, '#ffe08f');
  for (const y of [17, 20, 23]) rect(128, y, 21, 1, '#4d1f36');
  for (const [x, y] of [[112, 24], [119, 21], [126, 27]]) {rect(x, y, 1, 1, '#2a1330'); rect(x + 1, y + 1, 1, 1, '#2a1330'); rect(x + 2, y, 1, 1, '#2a1330')}
  ridge(x => 41 - 9 * Math.max(0, Math.sin((x - 40) / 18)) - 3 * Math.sin(x / 6) - (x > 150 ? 5 * Math.max(0, Math.sin((x - 150) / 10)) : 0), '#5a2236');
  ridge(x => 49 - 3 * Math.sin(x / 9 + 1) - 2 * Math.sin(x / 4), '#371428');
  for (const x of [152, 158, 163, 182, 188, 194]) pine(x, 52, 7 + (x % 3), '#24101e');
 } else if (provider === 'codex') {
  bands(['#06171d', '#082027', '#0b2a2e', '#0e3434', '#113f39', '#15493e', '#195443', '#1e6048']);
  stars(30, 40, 26, ['#9bffd2', '#e6fff3']);
  disc(137, 11, 5, '#d9ffe9'); disc(139, 10, 4, '#082027');
  let x = 52;
  while (x < W) {const w = 6 + Math.floor(rnd() * 7), h = 10 + Math.floor(rnd() * 13); rect(x, 52 - h, w, h + 10, '#0b3530'); for (let wy = 54 - h; wy < 50; wy += 3) for (let wx = x + 1; wx < x + w - 1; wx += 2) if (rnd() > .55) rect(wx, wy, 1, 1, rnd() > .7 ? '#e8ffa6' : '#7dffb9'); x += w + 2}
  for (let p = 0; p < W; p += 5) pine(p + 2, 58, 6 + Math.floor(rnd() * 5), '#05201a');
  for (let i = 0; i < 9; i++) rect(60 + Math.floor(rnd() * 138), 38 + Math.floor(rnd() * 12), 1, 1, '#c8ff8a', 'twinkle');
 } else {
  bands(['#0d0a28', '#120d33', '#170f3e', '#1c1349', '#211654', '#271a5f', '#2d1e6a', '#33226f']);
  stars(80, 0, 46, ['#efe6ff', '#b9a6ff', '#ffffff']);
  disc(140, 15, 8, '#8f6cf2'); disc(138, 13, 6, '#a98bff'); disc(136, 11, 2, '#cdbbff');
  for (let i = -15; i <= 15; i++) rect(140 + i, 16 + Math.round(-i * .28), 1, 1, Math.abs(i) < 8 ? '#e2d6ff' : '#bca8ff');
  disc(108, 26, 2, '#d9cff7');
  ridge(x => 50 - 4 * Math.abs(Math.sin(x / 13)) - 2 * Math.sin(x / 5), '#120c33');
  ridge(x => 56 - 2 * Math.abs(Math.sin(x / 8 + 2)), '#0a0722');
  for (const [cx, cy] of [[120, 58], [150, 59], [184, 58]]) rect(cx, cy, 3, 1, '#1d1550');
 }
 return s;
}
/* The TokenTV cube mascot for the Pixel Retro banner (36×32 logical pixels). */
function retroMascot() {
 const s = svgNode('svg', {viewBox:'0 0 44 34', 'shape-rendering':'crispEdges', class:'mascot-art'});
 const r = (x, y, w, h, fill, cls) => {const n = svgNode('rect', {x, y, width:w, height:h, fill}); if (cls) n.setAttribute('class', cls); s.append(n)};
 const O = '#151238', C = '#fff1d6', D = '#e3c79c', N = '#1c2a63', M = '#7ff5c8', P = '#ff7aa8', Y = '#ffd86b';
 r(15, 1, 3, 3, P); r(15, 1, 1, 1, '#ffd0e0'); r(16, 4, 1, 4, O);
 r(5, 8, 22, 1, O); r(4, 9, 1, 16, O); r(27, 9, 1, 16, O); r(5, 25, 22, 1, O);
 r(5, 9, 22, 16, C); r(25, 10, 2, 15, D); r(5, 23, 22, 2, D); r(6, 10, 4, 1, '#ffffff');
 r(8, 11, 16, 10, O); r(9, 12, 14, 8, N); r(9, 12, 14, 1, '#25367a');
 r(12, 14, 2, 1, M); r(11, 15, 1, 1, M); r(14, 15, 1, 1, M); r(18, 14, 2, 1, M); r(17, 15, 1, 1, M); r(20, 15, 1, 1, M);
 r(14, 18, 4, 1, M); r(13, 17, 1, 1, M); r(18, 17, 1, 1, M); r(10, 17, 2, 1, P); r(20, 17, 2, 1, P);
 r(1, 15, 3, 1, O); r(1, 16, 1, 5, O); r(2, 16, 2, 4, C); r(1, 21, 3, 1, O);
 r(28, 13, 2, 2, O); r(29, 9, 2, 4, O); r(28, 5, 4, 1, O); r(27, 6, 1, 3, O); r(32, 6, 1, 3, O); r(28, 6, 4, 3, C); r(28, 9, 4, 1, O);
 r(8, 26, 1, 4, O); r(9, 26, 4, 3, '#2a2f6a'); r(13, 26, 1, 4, O); r(8, 30, 6, 1, O);
 r(18, 26, 1, 4, O); r(19, 26, 4, 3, '#2a2f6a'); r(23, 26, 1, 4, O); r(18, 30, 6, 1, O);
 for (const [x, y, w, h] of [[36,2,2,1],[39,2,2,1],[35,3,7,2],[36,5,5,1],[37,6,3,1],[38,7,1,1]]) r(x, y, w, h, '#ff5d8f', 'beat');
 for (const [x, y] of [[33, 13], [40, 18], [1, 3]]) {r(x, y - 1, 1, 3, Y, 'twinkle'); r(x - 1, y, 3, 1, Y, 'twinkle')}
 return s;
}
function buildStarfield() {
 const rnd = seeded(5), s = svgNode('svg', {viewBox:'0 0 480 300', preserveAspectRatio:'xMidYMid slice', 'shape-rendering':'crispEdges'});
 for (let i = 0; i < 140; i++) {const big = i % 17 === 0, r = svgNode('rect', {x:Math.floor(rnd() * 480), y:Math.floor(rnd() * 300), width:big ? 2 : 1, height:big ? 2 : 1, fill:['#ffffff', '#b9c8ff', '#ffe9a8'][i % 3]}); if (i % 4 === 0) r.setAttribute('class', 'twinkle'); r.style.animationDelay = (-rnd() * 4).toFixed(2) + 's'; s.append(r)}
 $('#starfield').append(s);
}
/* Sakura branch: tapered limbs, notched five-petal flowers and buds. */
function buildBranch() {
 const s = svgNode('svg', {viewBox:'0 0 620 440', preserveAspectRatio:'xMaxYMin meet'});
 const defs = svgNode('defs', {}), g = svgNode('radialGradient', {id:'petal-fill', cx:'50%', cy:'100%', r:'105%'});
 for (const [o, c] of [['0', '#fffafc'], ['.5', '#ffd9e4'], ['1', '#f59bb7']]) g.append(svgNode('stop', {offset:o, 'stop-color':c}));
 defs.append(g); s.append(defs);
 const limb = (d, w, c) => s.append(svgNode('path', {d, fill:'none', stroke:c, 'stroke-width':w, 'stroke-linecap':'round'}));
 limb('M640 26C574 40 520 66 470 104', 15, '#5e3540'); limb('M470 104C420 142 372 170 314 196', 10, '#6c3d48'); limb('M314 196C268 217 236 236 196 266', 6, '#7a4752');
 limb('M470 104C486 150 482 196 500 246', 6, '#6c3d48'); limb('M500 246C506 270 520 290 536 304', 3.5, '#7a4752');
 limb('M396 152C372 120 344 100 312 82', 5, '#6c3d48'); limb('M560 52C566 84 586 102 610 116', 4, '#6c3d48'); limb('M260 220C246 196 226 186 202 182', 3, '#7a4752');
 const flower = (x, y, r, rot) => {
  const f = svgNode('g', {transform:`translate(${x} ${y}) rotate(${rot}) scale(${r / 22})`});
  for (let i = 0; i < 5; i++) f.append(svgNode('path', {d:'M0 0C-7-4-11-14-7-21C-4-25-1-24 0-21C1-24 4-25 7-21C11-14 7-4 0 0Z', fill:'url(#petal-fill)', stroke:'#f2a7bd', 'stroke-width':.6, transform:`rotate(${i * 72})`}));
  for (let i = 0; i < 9; i++) {const a = i * 40 * Math.PI / 180, l = 6 + (i % 3); f.append(svgNode('path', {d:`M0 0L${(Math.cos(a) * l).toFixed(1)} ${(Math.sin(a) * l).toFixed(1)}`, stroke:'#d84a7a', 'stroke-width':.8})); f.append(svgNode('circle', {cx:(Math.cos(a) * l).toFixed(1), cy:(Math.sin(a) * l).toFixed(1), r:.9, fill:'#f7c25a'}))}
  f.append(svgNode('circle', {r:2.6, fill:'#e0507f'}));
  s.append(f);
 };
 const bud = (x, y, rot) => {const b = svgNode('g', {transform:`translate(${x} ${y}) rotate(${rot})`}); b.append(svgNode('ellipse', {cx:0, cy:-5, rx:3.6, ry:5.5, fill:'#f48fb1'}), svgNode('path', {d:'M-3.5-1 0 3 3.5-1 0 1Z', fill:'#7a4752'})); s.append(b)};
 for (const [x, y, r, rot] of [[590,44,23,10],[548,70,26,-14],[512,40,18,30],[468,112,25,4],[430,92,20,-30],[402,150,22,18],[356,170,24,-8],[318,124,19,26],[300,200,21,40],[262,214,18,-20],[228,244,20,12],[492,196,22,-12],[514,258,18,30],[544,300,15,-6],[600,112,17,22],[198,184,14,-24],[336,92,15,8]]) flower(x, y, r, rot);
 for (const [x, y, rot] of [[196,268,-140],[310,80,-60],[612,118,40],[538,306,150],[452,64,-20],[248,200,-80]]) bud(x, y, rot);
 $('#branch').append(s);
}
function buildPetals() {
 const rnd = seeded(9), box = $('#petals');
 for (let i = 0; i < 18; i++) {
  const p = el('i');
  p.style.cssText = `--x:${(rnd() * 100).toFixed(1)}vw;--drift:${(rnd() * 22 - 4).toFixed(1)}vw;--size:${(8 + rnd() * 9).toFixed(1)}px;--fall:${(14 + rnd() * 12).toFixed(1)}s;--sway:${(3 + rnd() * 3).toFixed(1)}s;--delay:${(-rnd() * 26).toFixed(1)}s;--turn:${Math.round(rnd() * 360)}deg`;
  box.append(p);
 }
}

function resetTime(epoch) {if (!Number.isFinite(epoch) || epoch <= 0) return '—'; let m = Math.ceil((epoch - Date.now() / 1000) / 60); if (m <= 0) return 'Awaiting reset'; return m >= 1440 ? `${Math.floor(m / 1440)}d ${Math.floor(m % 1440 / 60)}h` : `${Math.floor(m / 60)}h ${pad(m % 60)}m`}
function period(w) {if (!w) return 'QUOTA'; return w.label === 'BUDGET' ? 'CLI BUDGET' : w.label === 'WEEK' ? 'WEEKLY' : w.label === '5H' ? '5-HOUR' : String(w.label || 'QUOTA')}
function level(v) {return v < 50 ? 'low' : v < 80 ? 'medium' : v < 90 ? 'high' : 'critical'}
function levelText(v) {return v >= 100 ? 'Limit reached' : v >= 90 ? 'Near limit' : v >= 80 ? 'High usage' : v >= 50 ? 'Moderate' : 'Low usage'}
function gauge(value, label) {
 const g = el('div', undefined, 'meter');
 if (Number.isFinite(value)) {value = clamp(value); g.dataset.level = level(value); g.style.setProperty('--value', value + '%'); g.style.setProperty('--v', String(Math.max(1, value))); g.setAttribute('role', 'meter'); g.setAttribute('aria-label', label); g.setAttribute('aria-valuemin', '0'); g.setAttribute('aria-valuemax', '100'); g.setAttribute('aria-valuenow', String(value))}
 else {g.classList.add('unknown-meter'); g.setAttribute('aria-label', label + ' unavailable')}
 for (let i = 0; i < 10; i++) {const seg = el('span', undefined, 'meter-segment'), fill = el('span', undefined, 'meter-fill'); seg.style.setProperty('--i', String(i)); fill.style.setProperty('--fill', Number.isFinite(value) ? clamp((value - i * 10) * 10) + '%' : '0%'); seg.append(fill); g.append(seg)}
 return g;
}
function stat(key, value, cls) {const s = el('div', undefined, 'stat' + (cls ? ' ' + cls : '')); s.append(el('span', key, 'stat-k'), typeof value === 'string' ? el('span', value, 'stat-v') : value); return s}

function setTheme(theme) {
 const config = THEMES.find(t => t.id === theme) || THEMES[3];
 document.documentElement.dataset.theme = config.id; savePreference('tokentv.theme', config.id);
 $('#eyebrow').textContent = config.eyebrow; $('#eyebrow').hidden = !config.eyebrow;
 $('#page-title').textContent = config.title;
 $('#intro-note').textContent = config.note; $('#intro-note').hidden = !config.note;
 for (const b of document.querySelectorAll('[data-theme-choice]')) b.setAttribute('aria-pressed', String(b.dataset.themeChoice === config.id));
}
for (const t of THEMES) {
 const b = el('button', undefined, 'theme-button'); b.type = 'button'; b.dataset.themeChoice = t.id; b.setAttribute('aria-pressed', 'false');
 const sw = el('span', undefined, 'swatch'); sw.dataset.swatch = t.id; sw.setAttribute('aria-hidden', 'true'); sw.append(el('i'), el('i'), el('i'));
 b.append(sw, el('span', t.name, 'theme-name')); b.onclick = () => setTheme(t.id); $('#themes').append(b);
}
setTheme(readPreference('tokentv.theme', 'modern'));

function providerCard(provider, accounts) {
 let a = accounts.find(x => x.key === accountChoices[provider]) || accounts[0];
 if (!a) a = {key:provider, alias:provider.toUpperCase(), provider, status:'loading', windows:[]};
 const prior = $(`.provider-card[data-provider="${provider}"] .more-windows`);
 const stale = offline || a.status === 'stale';
 const valid = (a.windows || []).filter(w => Number.isFinite(w.used_percent));
 // A mismatched identity must not expose another person's quota as this account.
 const windows = a.status === 'identity_mismatch' ? [] : valid;
 const primary = windows.reduce((p, w) => !p || w.used_percent > p.used_percent ? w : p, null);
 const value = primary ? clamp(primary.used_percent) : null;
 const shell = el('div', undefined, 'card-shell'); shell.dataset.provider = provider;
 const card = el('article', undefined, 'provider-card');
 Object.assign(card.dataset, {provider, key:a.key, stale:String(stale), level:value === null ? 'unknown' : level(value)});
 const art = el('div', undefined, 'card-art'); art.setAttribute('aria-hidden', 'true'); art.append(scene(provider));
 const head = el('div', undefined, 'card-head'), logo = el('div', undefined, 'provider-icon'); logo.append(icon(provider), mascot(provider));
 const name = el('div', undefined, 'provider-name'); name.append(el('h2', provider.toUpperCase(), 'provider-title'), el('span', COMPANIES[provider], 'company'));
 const tabs = el('div', undefined, 'account-tabs'); tabs.setAttribute('role', 'group'); tabs.setAttribute('aria-label', provider.toUpperCase() + ' accounts');
 for (const row of accounts) {const letter = (row.alias || '').split(' ').at(-1); const b = el('button', letter, 'account-tab'); b.type = 'button'; b.dataset.account = row.key; b.title = row.alias; b.setAttribute('aria-label', row.alias); b.setAttribute('aria-pressed', String(row.key === a.key)); b.onclick = () => {accountChoices[provider] = row.key; savePreference('tokentv.accounts', accountChoices); renderAccounts(); $(`[data-account="${row.key}"]`)?.focus()}; tabs.append(b)}
 head.append(logo, name, tabs);
 const reading = el('div', undefined, 'reading'), meta = el('div', undefined, 'reading-meta');
 meta.append(el('span', period(primary) + ' USED', 'reading-label'));
 if (primary) meta.append(el('span', stale ? 'OLD · Last known usage' : levelText(value), 'level-label'));
 else meta.append(el('span', a.status === 'quota_unavailable' ? 'Connected. No quota reported.' : STATUS[a.status] || 'No reading available.', 'unknown-message'));
 const num = el('div', value === null ? '—' : undefined, 'percentage');
 if (value !== null) {const digits = el('span', String(Math.round(value)), 'pct-num'); digits.dataset.ghost = ghost(digits.textContent); num.append(digits, el('span', '%', 'percent-sign'))}
 reading.append(meta, num);
 const timer = el('div', undefined, 'timer'), until = el('span', primary ? resetTime(primary.resets_at) : '—', 'timer-value');
 if (/^[\ddh ]+$/.test(until.textContent)) until.dataset.ghost = ghost(until.textContent);
 timer.append(clockGlyph(), el('span', 'RESETS IN', 'timer-label'), until);
 const row = el('div', undefined, 'gauge'); row.append(gauge(value, a.alias + ' ' + period(primary) + ' used quota'), el('span', value === null ? '—' : Math.round(value) + '%', 'gauge-value'));
 card.append(art, head, reading, timer, row);
 const others = windows.filter(w => w !== primary);
 if (others.length) {
  const details = el('details', undefined, 'more-windows'); details.open = prior?.open || false;
  const named = period(others[0]) === 'CLI BUDGET' ? 'CLI budget' : period(others[0])[0] + period(others[0]).slice(1).toLowerCase();
  details.append(el('summary', others.length === 1 ? `${named} window` : `${others.length} more windows`));
  for (const w of others) {const line = el('div', undefined, 'window-detail'); line.append(el('span', period(w), 'window-name'), gauge(w.used_percent, a.alias + ' ' + period(w) + ' used quota'), el('span', Math.round(w.used_percent) + '%', 'window-percent'), el('span', resetTime(w.resets_at), 'window-timer')); details.append(line)}
  card.append(details);
 }
 const checked = stale ? a.last_success_at : a.fetched_at;
 let when = el('span', '—', 'stat-v');
 if (checked) {const d = new Date(checked * 1000); when = el('time', d.toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'}), 'stat-v'); when.dateTime = d.toISOString(); when.title = d.toLocaleString('en-GB')}
 const foot = el('div', undefined, 'card-foot');
 foot.append(stat('Account', a.alias || '—'), stat('Window', primary ? period(primary) : '—'), stat('Source', a.source === 'mini' ? 'Mini' : a.source ? 'Laptop link' : '—'), stat(stale ? 'Last good' : 'Checked', when), stat('Status', el('span', offline ? 'OFFLINE · Previous value' : STATUS[a.status] || 'Unknown', 'row-status stat-v'), 'stat-status'));
 card.append(foot); shell.append(card); return shell;
}
function renderAccounts() {
 if (!snapshot) return;
 const focused = document.activeElement?.dataset?.account, rows = Object.values(snapshot.accounts || {}), fragment = document.createDocumentFragment();
 for (const provider of PROVIDERS) fragment.append(providerCard(provider, rows.filter(a => a.provider === provider)));
 $('#providers').replaceChildren(fragment);
 const reporting = offline ? 0 : rows.filter(a => a.status === 'ok' && (a.windows || []).some(w => Number.isFinite(w.used_percent))).length;
 $('#account-count').textContent = pad(rows.length); $('#reporting-count').textContent = pad(reporting);
 $('#foot-reporting').textContent = `${reporting} / ${rows.length} reporting`;
 if (focused) {const b = [...document.querySelectorAll('[data-account]')].find(b => b.dataset.account === focused); b?.focus({preventScroll:true})}
}
async function update() {
 if (polling) return; polling = true;
 try {
  const r = await fetch('/snapshot', {cache:'no-store'}); if (!r.ok) throw Error();
  const data = await r.json(); if (!data.accounts || !Number.isFinite(data.updated_at)) throw Error();
  snapshot = data; offline = false;
  const staleCount = Object.values(data.accounts).filter(a => a.status === 'stale').length;
  $('#connection').textContent = staleCount ? `${staleCount} stale · Live server` : 'Live from Mini';
  $('#notice').hidden = !staleCount; $('#notice').textContent = staleCount + ' account' + (staleCount === 1 ? ' has' : 's have') + ' an older reading. Check the selected account’s source and last successful update.';
  $('#updated').textContent = data.updated_at ? 'Server checked ' + new Date(data.updated_at * 1000).toLocaleTimeString('en-GB') : 'Waiting for first reading';
  $('#signal').dataset.strength = staleCount ? '2' : '3';
 } catch {
  offline = true; $('#connection').textContent = 'Server offline'; $('#notice').hidden = false; $('#signal').dataset.strength = '0';
  $('#notice').textContent = snapshot ? 'Connection lost. Showing the last received readings as OLD.' : 'Cannot reach Mini. Retry after the connection is restored.';
  if (!snapshot) $('#providers').replaceChildren(el('p', 'No usage data received.', 'loading'));
 } finally {polling = false; document.body.dataset.offline = String(offline); renderAccounts()}
}
function tick() {
 const now = new Date(), t = $('#local-time');
 const iso = t.querySelector('.date-iso'), time = t.querySelector('.time');
 iso.textContent = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`; iso.dataset.ghost = '8888-88-88';
 t.querySelector('.date-long').textContent = now.toLocaleDateString('en-US', {month:'short', day:'2-digit', year:'numeric'}).toUpperCase();
 time.textContent = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`; time.dataset.ghost = '88:88:88';
}
$('#clock-zone').textContent = new Intl.DateTimeFormat('en-US', {timeZoneName:'short'}).formatToParts(new Date()).find(p => p.type === 'timeZoneName')?.value || 'Local';

function showClock(show) {$('#clock-panel').hidden = !show; $('#clock-toggle').setAttribute('aria-expanded', String(show)); if (show) {refreshDisplay(true); $('#close-clock').focus()} else $('#clock-toggle').focus()}
$('#clock-toggle').onclick = () => showClock($('#clock-panel').hidden); $('#close-clock').onclick = () => showClock(false);
let lastImageStyle = null, lastImageAt = 0;
function paintClock(forceImage = false) {
 const style = clockChoice || displayInfo?.style;
 $('#clock-style').disabled = applying || !displayInfo; $('#apply').disabled = applying || !displayInfo || (style === displayInfo.style && displayInfo.status !== 'error' && !clockError);
 $('#apply').textContent = applying ? 'Sending image…' : 'Apply to clock'; $('#apply').dataset.state = applying ? 'loading' : clockError || displayInfo?.status === 'error' ? 'error' : displayInfo?.status === 'ok' ? 'success' : 'default';
 $('#display-state').textContent = clockError ? 'Could not apply. Please retry.' : !displayInfo ? 'Clock status unavailable' : style !== displayInfo.style ? 'Preview only · Apply to send' : displayInfo.status === 'queued' ? 'Sending image…' : displayInfo.status === 'error' ? 'Clock upload failed. Please retry.' : displayInfo.status === 'preview_only' ? 'Preview only · No clock connected' : 'Image sent · ' + styleName(displayInfo.applied_style);
 if (style && !$('#clock-panel').hidden && (forceImage || style !== lastImageStyle || Date.now() - lastImageAt > 30000)) {lastImageStyle = style; lastImageAt = Date.now(); $('#frame').src = '/frame/0.jpg?style=' + encodeURIComponent(style) + '&t=' + lastImageAt; $('#frame').alt = styleName(style) + ' live clock preview'}
}
const styleName = s => s === 'retro' ? 'Pixel Retro' : s === 'hud' ? 'Sci-Fi HUD' : s ? s[0].toUpperCase() + s.slice(1) : 'Unknown';
let displayPolling = false;
async function refreshDisplay(forceImage = false) {if (displayPolling) return; displayPolling = true; try {const r = await fetch('/display', {cache:'no-store'}); if (!r.ok) throw Error(); const data = await r.json(); const dirty = displayInfo && clockChoice !== displayInfo.style; displayInfo = data; if (!clockChoice || !dirty) clockChoice = data.style; const select = $('#clock-style'); if (!select.options.length) for (const s of data.styles) {const o = el('option', styleName(s)); o.value = s; select.append(o)} select.value = clockChoice; paintClock(forceImage)} catch {$('#display-state').textContent = 'Clock status unavailable'} finally {displayPolling = false}}
$('#clock-style').onchange = e => {clockChoice = e.target.value; clockError = false; paintClock(true)};
$('#apply').onclick = async () => {if (applying || !clockChoice) return; applying = true; clockError = false; paintClock(); try {const r = await fetch('/display/style', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({style:clockChoice})}); if (!r.ok) throw Error(); displayInfo = await r.json()} catch {clockError = true} finally {applying = false; paintClock(true)}};
$('#frame').onerror = () => {$('#display-state').textContent = 'Clock preview unavailable. Reopen to retry.'};

$('#mascot').append(retroMascot()); buildStarfield(); buildBranch(); buildPetals(); tick();
update(); refreshDisplay(); setInterval(update, 30000); setInterval(tick, 1000); setInterval(() => {if (!$('#clock-panel').hidden) refreshDisplay()}, 5000);
