// TokenTV's mod for Claude Code. While Claude Code waits for you to answer a permission prompt, Clawd on your
// TokenTV clock raises a hand (then hops, then holds up a sign); when a turn is done, it bows. `/tokentv pet` and
// `/tokentv snack` give Clawd a pat or a snack, one loop of hearts or munching.
//
// It tells the TokenTV running on this computer one of five names and nothing else: `claude.ask` (a permission
// prompt is now waiting for you), `claude.answered` (you answered it, or it is over), `claude.end` (a turn ended),
// `claude.pet` and `claude.snack` (the two commands). Prompts, commands, their words, paths and ids stay in this
// file. TokenTV counts the waits of every session, so each session says once that its prompt opened and once that it
// closed.
//
// Nothing here is awaited on Claude Code's path: the requests go out in the background, one after another so they
// arrive in the order they happened, and when no TokenTV runs (or it does not answer) nothing happens at all. What
// is below lives as long as the session (one per session).

// TokenTV lets every wait go 30 minutes after the continuous wait began, at this ask or before it (its answer to the
// ask says how long that wait had lasted: TokenTV-Wait-Age). An answer after that would close another, newer wait
// there, so it is not sent; nor one that would come this close to it (it might land just after).
const EXPIRE_MS = 30 * 60 * 1000
const MARGIN_MS = 5000
const KEEP = 256 // calls already answered, remembered so a late repeat of one is not a new wait
const PATIENCE_MS = 2000 // the longest one request holds the next back (TokenTV answers in milliseconds)
const STALE_MS = 5000 // a moment that could not go out within this is dropped: news, not history

// `to` names the running TokenTV that counted the wait's ask; its answer goes to that one only, never to another
// (one started since, which never saw the ask, would close a wait of someone else's). `sent` is the ask's own
// request, which the answer waits for: TokenTV may count the ask however late it says so. `waited` is how long
// TokenTV's continuous wait had lasted when it took the ask (ms; none from a TokenTV that does not say).
type Wait = { agent: string | undefined; at: number; to?: string; sent?: Promise<unknown>; waited?: number }

const waits = new Map<string, Wait>() // tool_use_id -> a prompt this session announced and has not closed
const callers = new Map<string, string | undefined>() // tool_use_id -> the subagent making a call now, if one is
const answered: string[] = []
let interactive = true // false in `claude -p` and the SDK: nobody sits at a dialog there
let mode: string | undefined // the permission mode, when Claude Code says it (auto mode's classifier asks no one)
let lastTurn: string | undefined
let queue: Promise<void> = Promise.resolve() // what is told goes out in the order it happened

export function register(on: any) {
  on('session.start', async ($: any, e: any, next: any) => {
    interactive = e?.isInteractive !== false
    try {
      // `immediate`: a pat typed while Claude works goes at once, not after the turn (it touches nothing of it)
      await $.command.register({ name: 'tokentv', description: 'Pet Clawd on your TokenTV clock, or give it a snack',
                                 argumentHint: 'pet | snack', immediate: true })
    } catch {}
    return next(e)
  })

  // `/tokentv pet` and `/tokentv snack`: one name each to TokenTV, sent as the other moments are (in the
  // background: the command never waits for it). Anything else after /tokentv sends nothing; its words go nowhere.
  on('command.run', { command: 'tokentv' }, async ($: any, e: any) => {
    const word = String(e?.args ?? '').trim().toLowerCase()
    const moment = word === 'pet' ? 'claude.pet' : word === 'snack' ? 'claude.snack' : undefined
    if (!moment) return { text: 'Try /tokentv pet or /tokentv snack.' }
    if (await onWindows($)) return { text: 'On Windows the TokenTV mod sends nothing for now.' }
    if (!(await findTokenTV($).catch(() => undefined))) {
      return { text: 'No TokenTV is running on this computer: nothing was sent.' }
    }
    send($, moment)
    return { text: word === 'pet' ? 'A pat for Clawd, on its way to TokenTV.' : 'A snack for Clawd, on its way to TokenTV.' }
  })

  // Read only for the permission mode (auto mode's classifier, not a person, settles what the rules leave open):
  // as the session starts and again before each tool call, as Claude Code's settings hooks are told it.
  on('classic.SessionStart', noteMode)
  on('classic.PreToolUse', noteMode)

  // The decision on a call, with Claude Code's verdict passed on untouched. `ask` with nobody else to decide it
  // means the permission prompt is about to show: one wait, once per call however often it is seen.
  on('tool.check', async ($: any, e: any, next: any) => {
    const decided = await next(e)
    try {
      const id = e?.tool_use_id
      if (asksYou(decided, id) && !waits.has(id) && !answered.includes(id)) {
        const wait = { agent: e.agentId ?? callers.get(id), at: 0 }
        waits.set(id, wait)
        send($, 'claude.ask', wait)
      }
    } catch {}
    return decided
  })

  // Your answer, as it happens: Claude Code draws the asked call's row again the moment you answer, running (you
  // said yes) or with its result (you said no). Measured in Claude Code 2.1.289 (2026-11-01): the asked call's
  // `isRunning` turns true in the first ToolGroup drawing after "Yes", while the tool.call around it settles only
  // once the tool is done. Drawings come often: with no prompt open they are handed straight on, and none is changed.
  on('ui.render', { component: ['ToolGroup', 'ToolUse'] }, async ($: any, e: any, next: any) => {
    if (waits.size === 0) return next(e)
    try {
      const calls = e?.component === 'ToolGroup' ? e.props?.calls ?? [] : [e?.props] // a ToolUse row is one call
      for (const call of calls) {
        if (waits.has(call?.tool_use_id) && (call.isRunning === true || call.output != null)) {
          answer($, call.tool_use_id)
        }
      }
    } catch {}
    return next(e)
  })

  // The permission check, your answer and the tool all happen inside `next`: once it is back, the prompt is over
  // (the tool ran, or was refused, or the turn was cut short), if no drawing said so before. The call and its
  // result pass through untouched.
  on('tool.call', async ($: any, e: any, next: any) => {
    const id = e?.tool_use_id
    if (typeof id === 'string') callers.set(id, e.agentId) // tool.check carries it only from Claude Code 2.1.290
    try {
      return await next(e)
    } finally {
      callers.delete(id)
      answer($, id)
    }
  })

  // A turn's end closes its open prompts; the main turn's end, when it was not cut short, is a bow.
  on('turn.complete', async ($: any, e: any, next: any) => {
    try {
      for (const [id, wait] of [...waits]) if (wait.agent === e?.agentId) answer($, id)
      const id = e?.turnId
      if (!e?.agentId && !e?.isAborted && (id === undefined || id !== lastTurn)) {
        lastTurn = id
        send($, 'claude.end')
      }
    } catch {}
    return next(e)
  })

  on('session.end', async ($: any, e: any, next: any) => {
    try {
      for (const id of [...waits.keys()]) answer($, id) // sent as the rest are; TokenTV lets go of any left
    } catch {}
    return next(e)
  })
}

async function noteMode($: any, e: any, next: any) {
  if (typeof e?.permission_mode === 'string') mode = e.permission_mode
  return next(e)
}

function asksYou(decided: any, id: unknown) {
  if (!decided || decided.decision !== 'ask' || decided.decider) return false // a host program answers that one
  if (typeof id !== 'string' || id === '' || !interactive || mode === 'dontAsk') return false
  // In auto mode the classifier settles an ask, unless an ask rule or a PreToolUse hook asked for you.
  return mode !== 'auto' || Boolean(decided.rule || decided.hook)
}

function answer($: any, id: unknown) {
  if (typeof id !== 'string') return
  const wait = waits.get(id)
  if (!wait) return
  waits.delete(id)
  answered.push(id)
  if (answered.length > KEEP) answered.shift()
  send($, 'claude.answered', wait)
}

// In the background, never awaited by a hook: each moment waits for the one before it to be answered (or for
// PATIENCE_MS), so TokenTV takes them in the order they happened; one held up past STALE_MS is dropped.
function send($: any, moment: string, wait?: Wait) {
  const asked = clockNow($)
  asked.catch(() => {})
  queue = queue.then(() => deliver($, moment, asked, wait)).catch(() => {})
}

async function deliver($: any, moment: string, asked: Promise<number>, wait?: Wait) {
  if (wait && moment === 'claude.answered') {
    // The ask's own request first: TokenTV may say late that it counted it. Not past STALE_MS: a TokenTV that
    // never answers holds nothing up for long (and an ask it never confirmed is not answered).
    if (wait.sent) await within($, wait.sent, STALE_MS)
    if (wait.to === undefined) return // TokenTV never took the ask: nothing of it to close
    const began = wait.at - (wait.waited ?? 0) // the continuous wait at TokenTV, which this ask joined
    if ((await clockNow($)) - began >= EXPIRE_MS - MARGIN_MS) return // TokenTV has let this wait go by now
    // An answer whose ask was counted goes however late, or the wait would stay on the clock.
  } else if ((await clockNow($)) - (await asked) > STALE_MS) {
    return
  }
  const place = await findTokenTV($)
  if (!place) return
  if (wait && moment === 'claude.answered' && wait.to !== place.id) return // another TokenTV run never saw the ask
  const init = { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ moment }),
                 socketPath: place.socket }
  const sent = $.http.fetch(place.url, init).then((response: any) => {
    if (!wait || moment !== 'claude.ask' || !response?.ok) return
    wait.to = place.id
    const waited = Number(response.headers?.['tokentv-wait-age']) // seconds; absent from an older TokenTV
    if (Number.isFinite(waited) && waited >= 0) wait.waited = waited * 1000
  })
  const settled = sent.catch(() => {})
  if (wait && moment === 'claude.ask') {
    wait.at = await clockNow($)
    wait.sent = settled
  }
  await within($, settled, PATIENCE_MS)
}

// `work`, or nothing after `ms`: the host's clock, else the runtime's own timer where there is one, else `work`.
function within($: any, work: Promise<unknown>, ms: number) {
  const later = () =>
    typeof (globalThis as any).setTimeout === 'function'
      ? new Promise((done) => (globalThis as any).setTimeout(done, ms))
      : work
  let timer: Promise<unknown>
  try {
    timer = Promise.resolve($.clock.sleep(ms)).catch(later)
  } catch {
    timer = later()
  }
  return Promise.race([work, timer])
}

async function clockNow($: any) {
  try {
    return await $.clock.now()
  } catch {
    return Date.now()
  }
}

// Where the running TokenTV listens: its state folder beside the config `token-tv start` uses
// (<XDG_CONFIG_HOME or ~/.config>/token-tv/state), or beside TOKEN_TV_CONFIG for another config. TokenTV writes its
// address there while it runs (live.url) and, on Linux and macOS, a socket of its own (live.sock). A moment goes
// only over that socket, where it meets no proxy and cannot be redirected anywhere else (Claude Code 2.1.289,
// measured 2026-11-01: Content-Length, Host 127.0.0.1:port). Over TCP the same fetch takes a proxy set in its
// environment, even to 127.0.0.1, and follows a redirect wherever it points, whatever its options say (measured the
// same day): so with no socket nothing is sent, and a live.url alone, perhaps left from a TokenTV that stopped, its
// port another program's now, is never tried. TokenTV makes no socket on Windows: there nothing is sent for now,
// whatever the folder holds.
async function onWindows($: any) {
  return (await Promise.resolve().then(() => $.env.get('OS')).catch(() => undefined)) === 'Windows_NT'
}

async function findTokenTV($: any) {
  if ((await $.env.get('OS')) === 'Windows_NT') return undefined
  const home = (await $.env.get('HOME')) || (await $.env.get('USERPROFILE'))
  const config = await $.env.get('TOKEN_TV_CONFIG')
  let state: string | undefined
  if (config) {
    const path = /^~[\\/]/.test(config) && home ? home + config.slice(1) : config
    const cut = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
    state = (cut < 0 ? '' : path.slice(0, cut + 1)) + 'state'
  } else {
    const base = (await $.env.get('XDG_CONFIG_HOME')) || (home ? home + '/.config' : undefined)
    state = base ? base + '/token-tv/state' : undefined
  }
  if (!state) return undefined
  if (!absolute(state)) {
    // Claude Code takes a socket only by an absolute path (2.1.289 refuses `./state/live.sock`): a relative one is
    // made absolute from the folder the session started in, where the relative TOKEN_TV_CONFIG was set. Not the
    // session's current folder, which follows a `cd` the model runs. With no absolute folder: nothing is sent.
    const root = await Promise.resolve().then(() => $.session.root()).catch(() => undefined)
    if (!absolute(root)) return undefined
    state = root.replace(/[\\/]+$/, '') + '/' + state.replace(/^(\.[\\/])+/, '')
  }
  const text = await $.fs.read(state + '/live.url')
  const url = loopback(text)
  if (!url) return undefined
  // Which run of TokenTV this is: it writes live.url anew each time it starts.
  const stat = await $.fs.stat(state + '/live.url').catch(() => undefined)
  const id = String(text).trim() + '@' + (stat?.mtimeMs ?? '')
  const socket = state + '/live.sock'
  if (!(await $.fs.exists(socket))) return undefined
  return { url: url + '/moment', socket, id }
}

// A path from the root of a drive: /…, C:\… or C:/…, or \\server\share.
function absolute(path: unknown): path is string {
  return typeof path === 'string' && /^(\/|[A-Za-z]:[\\/]|\\\\)/.test(path)
}

// Only this computer: http to 127.0.0.1, localhost (sent as 127.0.0.1, never looked up) or [::1] with a port,
// and nothing else. Any other address, a user, a path or a query: not ours to send to.
function loopback(text: unknown) {
  const found = /^http:\/\/(127\.0\.0\.1|localhost|\[::1\]):(\d{1,5})$/.exec(String(text ?? '').trim())
  if (!found || Number(found[2]) < 1 || Number(found[2]) > 65535) return undefined
  return 'http://' + (found[1] === 'localhost' ? '127.0.0.1' : found[1]) + ':' + Number(found[2])
}
