// TokenTV's mod for Claude Code. While Claude Code waits for you to answer a permission prompt, Clawd on your
// TokenTV clock raises a hand (then hops, then holds up a sign); when a turn is done, it bows. `/tokentv pet` and
// `/tokentv snack` give Clawd a pat or a snack, one loop of hearts or munching. A risky command puts Clawd in the
// courtroom, a deleted file leaves a ghost about, a rude prompt turns its back, a failed tool makes it dizzy, a
// compaction makes it squeeze its head, and the readout says Claude Code's own thinking word while a turn runs.
// `/tokentv sound on` plays a short sound on this computer when a prompt waits for you and when a turn is done.
//
// It tells the TokenTV running on this computer a name and nothing else: `claude.ask` (a prompt is now waiting for
// you: a permission dialog, a question, a plan to approve), `claude.answered` (you answered it, or it is over), `claude.end` (a turn ended), `claude.stop`
// (a turn that showed a thinking word was cut short), `claude.pet` and `claude.snack` (the two commands),
// `claude.risky`, `claude.deleted`, `claude.rude`, `claude.calm`, `claude.failed`, `claude.compact`, and
// `claude.word:` with one word of letters (Claude Code's spinner word, `claude.word:PONDERING`). Prompts, commands,
// their words, paths, outputs and ids stay in this file, and are read only to decide which name it is: nothing of
// them is kept. TokenTV counts the waits of every session, so each session says once that its prompt opened and
// once that it closed. Sounds go to TokenTV not at all.
//
// Nothing here is awaited on Claude Code's path, nor changes or blocks anything there: the requests go out in the
// background, one after another so they arrive in the order they happened, and when no TokenTV runs (or it does not
// answer) nothing happens at all. What is below lives as long as the session (one per session); the sound setting
// alone is kept, in Claude Code's own store for this plugin.

// TokenTV lets every wait go 30 minutes after the continuous wait began, at this ask or before it (its answer to the
// ask says how long that wait had lasted: TokenTV-Wait-Age). An answer after that would close another, newer wait
// there, so it is not sent; nor one that would come this close to it (it might land just after).
const EXPIRE_MS = 30 * 60 * 1000
const MARGIN_MS = 5000
const KEEP = 256 // calls already answered, remembered so a late repeat of one is not a new wait
const PATIENCE_MS = 2000 // the longest one request holds the next back (TokenTV answers in milliseconds)
const STALE_MS = 5000 // a moment that could not go out within this is dropped: news, not history
const WORD = 'claude.word:' // and the spinner's word: one word of 1 to 14 letters A-Z, sent in capitals
const SAY_AGAIN_MS = 5 * 60 * 1000 // a word still on is said again this often (TokenTV lets a word go unheard 30 min)
const SOUNDS = { wait: 'sounds/wait.wav', done: 'sounds/done.wav' } // the plugin's own two short clips
const STORE_MS = 1000 // the longest the sound setting's store may take, read or written
// The most of a prompt and of a command read to tell which name it is (their head): a paste of megabytes would take
// a tenth of a second or more, and a shout or a risky command is short.
const PROMPT_READ = 64 * 1024
const COMMAND_READ = 128 * 1024

// `to` names the running TokenTV that counted the wait's ask; its answer goes to that one only, never to another
// (one started since, which never saw the ask, would close a wait of someone else's). `sent` is the ask's own
// request, which the answer waits for: TokenTV may count the ask however late it says so. `waited` is how long
// TokenTV's continuous wait had lasted when it took the ask (ms; none from a TokenTV that does not say).
type Wait = { agent: string | undefined; at: number; to?: string; sent?: Promise<unknown>; waited?: number }

const waits = new Map<string, Wait>() // tool_use_id -> a prompt this session announced and has not closed
// Calls whose check said `ask` and that are still going: tool_use_id -> the tool, its arguments and its loop. The
// prompt Claude Code then raises names the tool and the arguments, not the call. Held as they came (never copied),
// read only to tell which call a prompt is for, and let go as the call ends.
type Asked = { tool: unknown; input: unknown; agent: string | undefined }
const asked = new Map<string, Asked>()
const callers = new Map<string, string | undefined>() // tool_use_id -> the subagent making a call now, if one is
const answered: string[] = []
let interactive = true // false in `claude -p` and the SDK: nobody sits at a dialog there
let mode: string | undefined // the permission mode, where Claude Code says it (2.1.289 did; 2.1.321 does not)
let lastTurn: string | undefined
let queue: Promise<void> = Promise.resolve() // what is told goes out in the order it happened
// What a call that is still going has shown of itself, kept only till it ends: whether it asked you, ran (drawn
// running, or Claude Code's PostToolUseFailure for it), was cut short, or refused by a rule, a hook or auto mode.
const prompted = new Set<string>()
const ran = new Set<string>()
const cut = new Set<string>()
const denied = new Set<string>()
let turning = false // a main turn is going (turn.start to its turn.complete): the spinner's word is its
let said: string | undefined // the word this turn last sent...
let saidAt: number | undefined // ...and when
let sound = false // the sound setting as this session knows it (the store's, when it answers, wins)

export function register(on: any) {
  on('session.start', async ($: any, e: any, next: any) => {
    interactive = e?.isInteractive !== false
    try {
      // `immediate`: a pat typed while Claude works goes at once, not after the turn (it touches nothing of it)
      await $.command.register({ name: 'tokentv',
                                 description: 'Pet Clawd on your TokenTV clock, give it a snack, or turn its sounds on or off',
                                 argumentHint: 'pet | snack | sound on | sound off', immediate: true })
    } catch {}
    return next(e)
  })

  // `/tokentv pet` and `/tokentv snack`: one name each to TokenTV, sent as the other moments are (in the
  // background: the command never waits for it). `/tokentv sound on` and `/tokentv sound off`: this computer's
  // sounds, nothing to TokenTV. Anything else after /tokentv sends nothing; its words go nowhere.
  on('command.run', { command: 'tokentv' }, async ($: any, e: any) => {
    const word = String(e?.args ?? '').trim().toLowerCase()
    const setting = /^sound\s+(on|off)$/.exec(word)
    if (setting) {
      sound = setting[1] === 'on'
      try {
        await within($, Promise.resolve($.store.set('sound', sound)), STORE_MS)
      } catch {}
      return { text: sound ? 'Sounds on: a short sound on this computer when Claude Code waits for you and when a ' +
                             'turn is done (Claude Code plays it on macOS; a Linux or Windows terminal stays silent).'
                           : 'Sounds off.' }
    }
    const moment = word === 'pet' ? 'claude.pet' : word === 'snack' ? 'claude.snack' : undefined
    if (!moment) return { text: 'Try /tokentv pet, /tokentv snack, or /tokentv sound on|off.' }
    if (await onWindows($)) return { text: 'On Windows the TokenTV mod sends nothing for now.' }
    if (!(await findTokenTV($).catch(() => undefined))) {
      return { text: 'No TokenTV is running on this computer: nothing was sent.' }
    }
    send($, moment)
    return { text: word === 'pet' ? 'A pat for Clawd, on its way to TokenTV.' : 'A snack for Clawd, on its way to TokenTV.' }
  })

  // Read only for the permission mode, where Claude Code says it: as the session starts and again before each tool
  // call (2.1.289). Claude Code 2.1.321 says neither; there the prompt itself tells (PermissionRequest, below).
  on('classic.SessionStart', noteMode)
  on('classic.PreToolUse', async ($: any, e: any, next: any) => {
    if (typeof e?.permission_mode === 'string') mode = e.permission_mode
    const verdict = await next(e)
    try {
      if (typeof verdict?.deny === 'string') note(denied, e?.tool_use_id) // a settings hook refused the call
    } catch {}
    return verdict
  })

  // A call that failed: one loop of Clawd dizzy, if it ran (not one you refused, nor one cut short). Claude Code
  // says which of its failures were interruptions; and when auto mode's classifier (or a rule) refused one.
  on('classic.PostToolUseFailure', async ($: any, e: any, next: any) => {
    try {
      note(e?.is_interrupt === true ? cut : ran, e?.tool_use_id)
    } catch {}
    return next(e)
  })
  on('classic.PermissionDenied', async ($: any, e: any, next: any) => {
    try {
      note(denied, e?.tool_use_id)
    } catch {}
    return next(e)
  })

  // The decision on a call, with Claude Code's verdict passed on untouched. `ask` is put to the mode's decider, and
  // that is you only sometimes: in auto mode (the default from Claude Code 2.1.3xx) the classifier settles most
  // asks within a second (measured in 2.1.321, 2026-11-11: every Bash call's check said `ask`, approver `person`,
  // and no dialog came). So an ask is only remembered here, till the call ends; the prompt is told below. An older
  // Claude Code that says its mode instead of who answers (2.1.289) is taken at its word, as before.
  on('tool.check', async ($: any, e: any, next: any) => {
    const decided = await next(e)
    try {
      const id = e?.tool_use_id
      if (decided?.decision === 'deny') note(denied, id)
      if (mayAskYou(decided, e) && callers.has(id)) {
        const agent = e.agentId ?? callers.get(id)
        asked.set(id, { tool: e.tool, input: e.input, agent })
        if (mode !== undefined && e.approver === undefined && asksYou(decided)) open($, id, agent)
      }
    } catch {}
    return decided
  })

  // The prompt itself: Claude Code raises PermissionRequest as it puts a call to you, a permission dialog, a
  // question (AskUserQuestion) or a plan to approve, in every mode, and never for a call the classifier settles
  // (measured in 2.1.321: about 20 ms after the check; its settings hooks answer nothing and the dialog stays
  // yours). One wait, once per call however often it is raised. The request passes on untouched.
  on('classic.PermissionRequest', async ($: any, e: any, next: any) => {
    try {
      const id = raisedFor(e)
      if (id !== undefined) open($, id, asked.get(id)?.agent)
    } catch {}
    return next(e)
  })

  // Your answer, as it happens: Claude Code draws the asked call's row again the moment you answer, running (you
  // said yes) or with its result (you said no). Measured in Claude Code 2.1.289 (2026-11-01): the asked call's
  // `isRunning` turns true in the first ToolGroup drawing after "Yes", while the tool.call around it settles only
  // once the tool is done. Drawings come often: with no prompt open they are handed straight on, and none is changed.
  on('ui.render', { component: ['ToolGroup', 'ToolUse'] }, async ($: any, e: any, next: any) => {
    if (waits.size === 0 && callers.size === 0) return next(e)
    try {
      const calls = e?.component === 'ToolGroup' ? e.props?.calls ?? [] : [e?.props] // a ToolUse row is one call
      for (const call of calls) {
        if (call?.isRunning === true) note(ran, call.tool_use_id) // (it ran: a failure now is the tool's own)
        if (call?.isInterrupted === true) note(cut, call.tool_use_id)
        if (waits.has(call?.tool_use_id) && (call.isRunning === true || call.output != null)) {
          answer($, call.tool_use_id)
        }
      }
    } catch {}
    return next(e)
  })

  // The spinner's word while a turn runs (`Pondering`, as Claude Code samples it for the turn): one word of up to
  // 14 letters goes to TokenTV, once (and again every SAY_AGAIN_MS while it stays); anything else is left out. The
  // drawing passes on untouched.
  on('ui.render', { component: 'Spinner' }, async ($: any, e: any, next: any) => {
    try {
      const word = e?.props?.word
      if (turning && typeof word === 'string' && /^[A-Za-z]{1,14}$/.test(word)) say($, word.toUpperCase())
    } catch {}
    return next(e)
  })

  on('turn.start', async ($: any, e: any, next: any) => {
    turning = true // (a subagent's run raises no turn.start)
    said = saidAt = undefined
    return next(e)
  })

  // A prompt you typed (here, or from your phone through Remote Control): in capitals, or with a swear in it, Clawd
  // turns its back (`claude.rude`); any other turns it round (`claude.calm`). The prompt is read for that and
  // passed on untouched; nothing of it is kept or sent.
  on('prompt.submit', async ($: any, e: any, next: any) => {
    try {
      const from = e?.origin?.kind
      if (typeof e?.text === 'string' && (from === undefined || from === 'composer' || from === 'bridge')) {
        send($, rude(e.text.slice(0, PROMPT_READ)) ? 'claude.rude' : 'claude.calm')
      }
    } catch {}
    return next(e)
  })

  // A compaction of the main conversation, once done (not one computed ahead to keep, nor a subagent's): one loop
  // of Clawd squeezing its head. What was compacted passes on untouched.
  on('session.compact', async ($: any, e: any, next: any) => {
    const done = await next(e)
    try {
      if (!e?.agentId && e?.trigger !== 'precompute' && Array.isArray(done?.messages)) send($, 'claude.compact')
    } catch {}
    return done
  })

  // The permission check, your answer and the tool all happen inside `next`: once it is back, the prompt is over
  // (the tool ran, or was refused, or the turn was cut short), if no drawing said so before. A Bash command is read
  // as it is called, for its risk (the courtroom, said at once) and whether it deletes files (a ghost, said once it
  // succeeded); a call of any tool that ran and failed is a dizzy Clawd. The call and its result pass through
  // untouched.
  on('tool.call', async ($: any, e: any, next: any) => {
    const id = e?.tool_use_id
    if (typeof id === 'string') callers.set(id, e.agentId) // tool.check carries it only from Claude Code 2.1.290
    let kinds: Kinds | undefined
    try {
      kinds = e?.tool === 'Bash' && typeof e?.command === 'string' ? judged(e.command.slice(0, COMMAND_READ)) : undefined
      if (kinds?.risky) send($, 'claude.risky')
    } catch {}
    let result: any
    try {
      result = await next(e)
      return result
    } finally {
      callers.delete(id)
      asked.delete(id)
      answer($, id)
      try {
        finished($, id, kinds, result, next?.signal)
      } catch {}
    }
  })

  // A turn's end closes its open prompts; the main turn's end, when it was not cut short, is a bow (and its sound,
  // if on). One cut short that showed a word says so, so its word goes too.
  on('turn.complete', async ($: any, e: any, next: any) => {
    try {
      for (const [id, wait] of [...waits]) if (wait.agent === e?.agentId) answer($, id)
      const id = e?.turnId
      if (!e?.agentId) {
        const spoke = said !== undefined
        turning = false
        said = saidAt = undefined
        if (id === undefined || id !== lastTurn) {
          if (!e?.isAborted) {
            lastTurn = id
            send($, 'claude.end')
            cue($, 'done')
          } else if (spoke) {
            lastTurn = id
            send($, 'claude.stop')
          }
        }
      }
    } catch {}
    return next(e)
  })

  on('session.end', async ($: any, e: any, next: any) => {
    try {
      for (const id of [...waits.keys()]) answer($, id) // sent as the rest are; TokenTV lets go of any left
      if (turning && said !== undefined) send($, 'claude.stop') // ended mid-turn: its word goes
      turning = false
      said = saidAt = undefined
    } catch {}
    return next(e)
  })
}

// A call still going (tool.call has it): what it showed of itself, till it ends.
function note(set: Set<string>, id: unknown) {
  if (typeof id === 'string' && callers.has(id)) set.add(id)
}

// A call is over with `result`: a Bash call that deleted files and succeeded leaves a ghost; any call that ran and
// failed (Claude Code says isError) makes Clawd dizzy, but not one refused (by you, a rule, a hook or auto mode),
// cut short or abandoned. What the call showed of itself is let go here.
function finished($: any, id: unknown, kinds: Kinds | undefined, result: any, signal: any) {
  const key = typeof id === 'string' ? id : ''
  const shown = { asked: prompted.has(key), ran: ran.has(key), cut: cut.has(key), denied: denied.has(key) }
  for (const set of [prompted, ran, cut, denied]) set.delete(key)
  if (!result || typeof result !== 'object' || typeof result.deny === 'string' || signal?.aborted === true) return
  if (result.isError === true) {
    if (!shown.cut && !shown.denied && (!shown.asked || shown.ran)) send($, 'claude.failed')
  } else if (kinds?.deletes) {
    send($, 'claude.deleted')
  }
}

// The spinner's word: sent when it is new this turn, and again only once SAY_AGAIN_MS has gone by.
function say($: any, word: string) {
  if (word !== said) {
    said = word
    saidAt = undefined
    send($, WORD + word)
    clockNow($).then((now) => { if (said === word) saidAt = now }, () => {})
    return
  }
  clockNow($).then((now) => {
    if (said === word && saidAt !== undefined && now - saidAt >= SAY_AGAIN_MS) {
      saidAt = now
      send($, WORD + word)
    }
  }, () => {})
}

// A short sound on this computer (`wait` or `done`), if the setting is on: Claude Code's own player plays the
// plugin's clip; nothing goes to TokenTV for it, and nothing waits for it. Where there is no player (a Linux or
// Windows terminal), or it fails, nothing sounds.
function cue($: any, which: 'wait' | 'done') {
  soundOn($)
    .then((on) => (on ? $.audio.play({ asset: SOUNDS[which] }) : undefined))
    .catch(() => {})
}

// The sound setting: the store's (so a change in one session holds in the others), else this session's.
async function soundOn($: any) {
  try {
    const kept = await within($, Promise.resolve($.store.get('sound')), STORE_MS)
    if (typeof kept === 'boolean') return kept
  } catch {}
  return sound
}

async function noteMode($: any, e: any, next: any) {
  if (typeof e?.permission_mode === 'string') mode = e.permission_mode
  return next(e)
}

// An ask a person could be put: not one a host program answers, nor in a run with nobody at a dialog.
function mayAskYou(decided: any, e: any) {
  if (!decided || decided.decision !== 'ask' || decided.decider || e?.approver === 'host') return false
  const id = e?.tool_use_id
  return typeof id === 'string' && id !== '' && interactive && mode !== 'dontAsk'
}

// Where Claude Code says its mode (2.1.289): in auto mode the classifier settles an ask, unless an ask rule or a
// PreToolUse hook asked for you; in any other the ask is yours.
function asksYou(decided: any) {
  return mode !== 'auto' || Boolean(decided.rule || decided.hook)
}

// A prompt is open for the call: one wait, once per call (its sound, if on, when it is this session's first open).
function open($: any, id: string, agent: string | undefined) {
  if (waits.has(id) || answered.includes(id)) return
  const wait = { agent, at: 0 }
  const first = waits.size === 0
  waits.set(id, wait)
  note(prompted, id)
  send($, 'claude.ask', wait)
  if (first) cue($, 'wait')
}

// The call a prompt is for. Among the calls whose check asked and that are still going, of that tool and loop: the
// earliest with these arguments that has no prompt yet (two calls alike each get their own); none, if those with
// these arguments all have theirs (raised again: nothing new); and if the arguments tell none apart, the earliest
// that has no prompt yet.
function raisedFor(e: any): string | undefined {
  if (!interactive) return undefined
  let earliest: string | undefined
  let again = false
  for (const [id, call] of asked) {
    if (call.tool !== e?.tool_name) continue
    if (call.agent !== undefined && e?.agent_id !== undefined && call.agent !== e.agent_id) continue
    const prompted = waits.has(id) || answered.includes(id)
    if (alike(call.input, e?.tool_input)) {
      if (!prompted) return id
      again = true
    } else if (earliest === undefined && !prompted) {
      earliest = id
    }
  }
  return again ? undefined : earliest
}

// The same arguments as far as both say: every field both have is equal, and they share one (a prompt's arguments
// may carry more fields than the check's). Strings are compared where they are, never copied.
function alike(a: any, b: any) {
  if (a === b) return true
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object') return false
  let shared = 0
  for (const key of Object.keys(a)) {
    if (!(key in b)) continue
    shared++
    const one = a[key]
    const other = b[key]
    if (one === other) continue
    if (!one || !other || typeof one !== 'object' || typeof other !== 'object') return false
    if (JSON.stringify(one) !== JSON.stringify(other)) return false
  }
  return shared > 0 || (Object.keys(a).length === 0 && Object.keys(b).length === 0)
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

// --- Which name: the prompt and the Bash command, read here and kept nowhere -------------------------------------

// e7: a prompt in capitals (at least CAPS_MIN letters, four in five or more of them capitals; a letter of a script
// without capitals, Hangul say, counts as a letter that is not one) or with a swear in it: SWEAR_EN, whole words in
// any case; SWEAR_KO, words starting so, but not the everyday words in SWEAR_KO_NOT. The owner's lists, one place.
const CAPS_MIN = 8
const SWEAR_EN = new Set(['fuck', 'fucks', 'fucked', 'fucking', 'fucker', 'motherfucker', 'shit', 'shitty', 'bullshit',
                          'damn', 'dammit', 'damnit', 'goddamn', 'wtf', 'stfu', 'bitch', 'asshole', 'bastard'])
const SWEAR_KO = ['씨발', '시발', '씨팔', 'ㅅㅂ', 'ㅆㅂ', '개새끼', '병신', '지랄', '존나', '좆']
const SWEAR_KO_NOT = ['시발점', '시발역', '병신년']

function rude(text: string) {
  const letters = text.match(/\p{L}/gu) ?? []
  const capitals = letters.filter((c) => /\p{Lu}|\p{Lt}/u.test(c)).length
  if (letters.length >= CAPS_MIN && capitals * 5 >= letters.length * 4) return true
  return (text.match(/[\p{L}\p{M}]+/gu) ?? []).some((word) => SWEAR_EN.has(word.toLowerCase()) ||
    (SWEAR_KO.some((stem) => word.startsWith(stem)) && !SWEAR_KO_NOT.some((benign) => word.startsWith(benign))))
}

// e3, e4: what a Bash command does, read as a shell would (quotes, comments, here-documents and redirections are
// data; `;`, `&&`, `|`, `$(…)`, backquotes, `bash -c`, `eval`, `find -exec` and wrappers such as `sudo` or `env`
// lead to commands; `command -v` and the like only look one up). Risky: `rm` recursive and forced, `git push
// --force` (`-f`, `--force-with-lease`, a `+refspec`), `git reset --hard`, `git clean` forced with directories (not
// a dry run), `DROP TABLE` or `DROP DATABASE` given to a database client as SQL (not in a string or a comment),
// `mkfs`, `dd of=/dev/…`, `chmod -R 777 /`. Deleting: `rm`, `git rm` (not `--cached`, not a dry run), `find …
// -delete` (or `-exec rm`), `unlink`, each with something to delete. Read in one pass: a command of many parts takes
// no longer than its length says.
type Kinds = { risky: boolean; deletes: boolean }
type Command = { words: string[]; input: string[]; pipe: number }

const PREFIXES = new Set(['if', 'then', 'else', 'elif', 'do', 'while', 'until', '!', '{'])
// A wrapper runs the command after it: its options that take a value, and the words it takes before the command;
// with an option `looks` matches, it only looks the command up (`command -v rm`) and runs nothing.
const WRAPPERS = new Map<string, { takes: string[]; operands: number; looks?: RegExp }>(Object.entries({
  sudo: { takes: ['-u', '-g', '-C', '-D', '-h', '-p', '-r', '-t', '-U', '-T', '--user', '--group', '--chdir', '--host',
                  '--prompt', '--role', '--type', '--other-user', '--command-timeout', '--close-from'], operands: 0 },
  doas: { takes: ['-u', '-C'], operands: 0 },
  env: { takes: ['-u', '-C', '-S', '--unset', '--chdir', '--split-string'], operands: 0 },
  command: { takes: [], operands: 0, looks: /^-[A-Za-z]*[vV]/ },
  builtin: { takes: [], operands: 0 },
  exec: { takes: ['-a'], operands: 0 },
  nohup: { takes: [], operands: 0 },
  time: { takes: ['-f', '-o', '--format', '--output'], operands: 0 },
  nice: { takes: ['-n', '--adjustment'], operands: 0 },
  ionice: { takes: ['-c', '-n', '-p', '-P', '-u'], operands: 0 },
  timeout: { takes: ['-s', '-k', '--signal', '--kill-after'], operands: 1 },
  setsid: { takes: [], operands: 0 },
  stdbuf: { takes: ['-i', '-o', '-e'], operands: 0 },
  xargs: { takes: ['-I', '-n', '-P', '-L', '-s', '-d', '-E', '-a', '--max-args', '--max-procs', '--max-lines',
                   '--max-chars', '--delimiter', '--eof', '--arg-file', '--replace'], operands: 0 },
}))
const SHELLS = new Set(['bash', 'sh', 'zsh', 'dash', 'ksh'])
// The commands judge() reads (with mkfs.<kind> and the shells): any other runs nothing of the lists.
const JUDGED = new Set(['rm', 'unlink', 'git', 'find', 'dd', 'chmod', 'eval', ...SHELLS])
const SQL = new Set(['psql', 'mysql', 'mariadb', 'sqlite3', 'sqlcmd', 'duckdb', 'clickhouse', 'clickhouse-client',
                     'cockroach', 'pgcli', 'mycli', 'litecli', 'usql', 'sqlplus', 'snowsql', 'bq', 'trino', 'beeline'])
const HASH_COMMENTS = new Set(['mysql', 'mariadb', 'mycli']) // `#` starts a comment there (elsewhere an operator)
const CLIENT = 1 // a pipeline's marks (judged)
const HASH = 2
const DROPS = 4
const OPEN_ALL = new Set(['777', '0777', 'a+rwx', 'a=rwx', 'ugo+rwx', 'ugo=rwx'])
const GIT_VALUED = new Set(['-C', '-c', '--git-dir', '--work-tree', '--namespace', '--super-prefix', '--config-env'])
// find's tests and actions that take the next word as their value (a pattern, a name, a format, a file): never an
// action itself, as `-name '-delete'` is not one. (`-fprintf` takes two, `-newerXY` one.)
const FIND_VALUED = new Set(['-name', '-iname', '-path', '-ipath', '-wholename', '-iwholename', '-regex', '-iregex',
  '-lname', '-ilname', '-newer', '-anewer', '-cnewer', '-samefile', '-perm', '-type', '-xtype', '-user', '-group',
  '-uid', '-gid', '-size', '-mtime', '-atime', '-ctime', '-mmin', '-amin', '-cmin', '-used', '-links', '-inum',
  '-maxdepth', '-mindepth', '-fstype', '-context', '-printf', '-fprint', '-fprint0', '-fls', '-regextype',
  '-files0-from'])

function judged(source: string, depth = 0): Kinds {
  const kinds = { risky: false, deletes: false }
  if (depth > 4) return kinds // (`bash -c` within `bash -c` within …: enough)
  const commands: Command[] = []
  const pipes = { n: 0 }
  parse(source, { i: 0 }, '', commands, pipes)
  // Each pipeline's marks: a database client is in it (CLIENT; HASH when `#` starts a comment there), it says "drop"
  // somewhere (DROPS). A DROP counts only in a pipeline with both, as SQL one of its clients reads.
  const marks = new Uint8Array(pipes.n)
  for (const command of commands) {
    const found = unwrapped(command.words)
    if (found && SQL.has(found.name)) marks[command.pipe] |= CLIENT | (HASH_COMMENTS.has(found.name) ? HASH : 0)
    if (command.words.some(saysDrop) || command.input.some(saysDrop)) marks[command.pipe] |= DROPS
    judge(found, kinds, depth)
  }
  const texts = new Map<number, string[]>()
  for (const command of commands) {
    if ((marks[command.pipe] & (CLIENT | DROPS)) !== (CLIENT | DROPS)) continue
    let parts = texts.get(command.pipe)
    if (!parts) texts.set(command.pipe, (parts = []))
    for (const word of command.words) parts.push(given(word))
    for (const text of command.input) parts.push(text)
  }
  for (const [pipe, parts] of texts) {
    if (drops(parts.map((text) => sqlRead(text, (marks[pipe] & HASH) !== 0)))) kinds.risky = true
  }
  return kinds
}

function saysDrop(text: string) {
  return text.length >= 4 && /drop/i.test(text)
}

// What of a word in a database client's pipeline may be SQL: an option's value (`--command=…`), not the option.
function given(word: string) {
  if (word[0] !== '-') return word
  const valued = /^--?[A-Za-z][\w-]*=/.exec(word)
  return valued ? word.slice(valued[0].length) : /^-\S*$/.test(word) ? '' : word
}

// DROP TABLE or DROP DATABASE as SQL in the texts read (sqlRead), not in a string or a comment; but where the SQL
// runs a string as a statement (EXECUTE, PREPARE, a DO block), a DROP in its strings counts too.
function drops(read: [string, string][]) {
  const dynamic = read.some(([bare]) => /\b(EXECUTE|PREPARE)\b|(^|;)\s*DO\b/i.test(bare))
  return /\bDROP\s+(TABLE|DATABASE)\b/i.test(read.map((both) => both[dynamic ? 1 : 0]).join(' '))
}

// `text` read as SQL, its comments left out (`-- …`, `/* … */`, and `# …` where `hash`): [without its string
// literals and quoted names, with them]. Those are `'…'` and `"…"` (a backslash escapes in them), `` `…` `` and
// `$tag$…$tag$`. One pass: each literal or comment is skipped whole.
const DOLLAR_TAG = /\$(?:[A-Za-z_]\w{0,62})?\$/y

function sqlRead(text: string, hash: boolean): [string, string] {
  if (!/['"`$#/-]/.test(text)) return [text, text] // (nothing of the kind in it)
  const bare: string[] = []
  const full: string[] = []
  let from = 0 // the SQL not yet kept starts here
  let i = 0
  while (i < text.length) {
    const c = text[i]
    let end = -1 // where the literal or comment starting at `i` ends
    let literal = false
    if (c === "'" || c === '"' || c === '`') {
      let j = i + 1
      while (j < text.length && text[j] !== c) j += text[j] === '\\' && c !== '`' ? 2 : 1
      end = Math.min(j + 1, text.length)
      literal = true
    } else if ((c === '-' && text[i + 1] === '-') || (c === '#' && hash)) {
      end = text.indexOf('\n', i)
      if (end < 0) end = text.length
    } else if (c === '/' && text[i + 1] === '*') {
      end = text.indexOf('*/', i + 2)
      end = end < 0 ? text.length : end + 2
    } else if (c === '$' && !/[\w$]/.test(text[i - 1] ?? ' ')) {
      DOLLAR_TAG.lastIndex = i
      const tag = DOLLAR_TAG.exec(text)?.[0]
      if (tag) {
        const close = text.indexOf(tag, i + tag.length)
        end = close < 0 ? text.length : close + tag.length
        literal = true
      }
    }
    if (end < 0) {
      i++
      continue
    }
    const sql = text.slice(from, i)
    bare.push(sql, ' ')
    full.push(sql, literal ? text.slice(i, end) : ' ')
    from = i = end
  }
  bare.push(text.slice(from))
  full.push(text.slice(from))
  return [bare.join(''), full.join('')]
}

// What the command `found` (unwrapped) runs, into `kinds`.
function judge(found: Found | undefined, kinds: Kinds, depth: number) {
  if (!found) return
  const name = found.name
  const mkfs = name.startsWith('mkfs') && /^mkfs(\.[A-Za-z0-9]+)?$/.test(name)
  if (!JUDGED.has(name) && !mkfs) return // (most commands)
  const args = found.words.slice(1)
  const either = (more: Kinds) => {
    kinds.risky ||= more.risky
    kinds.deletes ||= more.deletes
  }
  if (SHELLS.has(name)) {
    const at = args.findIndex((a) => /^-[A-Za-z]*c[A-Za-z]*$/.test(a))
    if (at >= 0 && typeof args[at + 1] === 'string') either(judged(args[at + 1], depth + 1))
    return
  }
  if (name === 'eval') return either(judged(args.join(' '), depth + 1))
  if (name === 'git') return git(args, kinds)
  if (name === 'dd') {
    if (args.some((a) => a.startsWith('of=/dev/'))) kinds.risky = true
    return
  }
  if (name === 'find') {
    for (let k = 0; k < args.length; k++) {
      const a = args[k]
      if (a === '-delete') kinds.deletes = true
      else if (a === '-fprintf') k += 2
      else if (FIND_VALUED.has(a) || /^-newer[aBcmt]{2}$/.test(a)) k++ // (its value, whatever it says)
      else if (['-exec', '-execdir', '-ok', '-okdir'].includes(a)) {
        let end = k + 1
        while (end < args.length && args[end] !== ';' && args[end] !== '+') end++
        judge(unwrapped(args.slice(k + 1, end)), kinds, depth)
        k = end
      }
    }
    return
  }
  const opts = options(args)
  const has = (short: string, long: string) => opts.short.has(short) || opts.long.has(long)
  const something = opts.operands.length > 0 || found.fed // (xargs gives it what to work on)
  if (name === 'rm' && something && !opts.long.has('help') && !opts.long.has('version')) {
    kinds.deletes = true
    if ((has('r', 'recursive') || opts.short.has('R')) && has('f', 'force')) kinds.risky = true
  } else if (name === 'unlink' && something) {
    kinds.deletes = true
  } else if (name === 'chmod') {
    const [mode, ...targets] = opts.operands
    if (has('R', 'recursive') && OPEN_ALL.has(mode ?? '') && targets.some((t) => t === '/' || t === '/*')) kinds.risky = true
  } else if (mkfs && opts.operands.length > 0) {
    kinds.risky = true
  }
}

function git(args: string[], kinds: Kinds) {
  let k = 0
  while (k < args.length && args[k].startsWith('-')) k += GIT_VALUED.has(args[k]) ? 2 : 1 // git's own options
  const sub = args[k]
  const opts = options(args.slice(k + 1))
  if (sub === 'push') {
    // forced by an option, or by a refspec after the remote that starts with `+` (`git push origin +main`)
    const plus = opts.operands.slice(1).some((ref) => ref.length > 1 && ref.startsWith('+'))
    if (opts.short.has('f') || opts.long.has('force') || opts.long.has('force-with-lease') || plus) kinds.risky = true
  } else if (sub === 'reset') {
    if (opts.long.has('hard')) kinds.risky = true
  } else if (sub === 'clean') {
    const force = opts.short.has('f') || opts.long.has('force')
    const dry = opts.short.has('n') || opts.long.has('dry-run')
    if (force && opts.short.has('d') && !dry) kinds.risky = true
  } else if (sub === 'rm') {
    const dry = opts.short.has('n') || opts.long.has('dry-run')
    if (!dry && !opts.long.has('cached') && opts.operands.length > 0) kinds.deletes = true
  }
}

// The words before `--` as short options (each letter) and long ones (name before any `=`), and the operands.
function options(args: string[]) {
  const short = new Set<string>()
  const long = new Set<string>()
  const operands: string[] = []
  let ended = false
  for (const a of args) {
    if (ended || a === '-' || !a.startsWith('-')) operands.push(a)
    else if (a === '--') ended = true
    else if (a.startsWith('--')) long.add(a.slice(2).split('=')[0])
    else for (const c of a.slice(1)) short.add(c)
  }
  return { short, long, operands }
}

// The command a simple command runs: past its variable assignments, the shell's words before a command (`if`,
// `then`, `!`, …) and wrappers with their options. `fed`: xargs gives it what to work on. None when it runs none
// (`command -v rm` only looks rm up).
type Found = { words: string[]; fed: boolean; name: string } // (name: the command's, its folder left out)

function unwrapped(words: string[]): Found | undefined {
  let k = 0
  let fed = false
  for (let guard = 0; guard < 32 && k < words.length; guard++) {
    const word = words[k]
    if (/^[A-Za-z_][A-Za-z0-9_]*=/.test(word) || PREFIXES.has(word)) {
      k++
      continue
    }
    const name = basename(word)
    const wrapper = WRAPPERS.get(name)
    if (!wrapper) break
    fed ||= name === 'xargs'
    k++
    while (k < words.length && words[k].startsWith('-') && words[k] !== '-') {
      const opt = words[k++]
      if (opt === '--') break
      if (wrapper.looks?.test(opt)) return undefined
      if (wrapper.takes.includes(opt)) k++
    }
    k += wrapper.operands
  }
  return k < words.length ? { words: k ? words.slice(k) : words, fed, name: basename(words[k]) } : undefined
}

function basename(word: string) {
  return word.slice(word.lastIndexOf('/') + 1)
}

// A shell's reading of `source` from `at.i` up to `stop` (`)` closing `$(`, a backquote) or its end: each simple
// command's words (unquoted), what it is fed (here-documents, here-strings) and its pipeline, into `out`.
function parse(source: string, at: { i: number }, stop: string, out: Command[], pipes: { n: number }) {
  let words: string[] = []
  let input: string[] = []
  let word = ''
  let has = false // a word has begun (an empty quoted one is a word)
  let route: 'arg' | 'file' | 'heredoc' | 'herestring' = 'arg' // where the next word goes, after a redirection
  let strip = false // `<<-`: the here-document's lines lose their leading tabs
  let depth = 0 // subshells open, `( … )`
  let pipe = pipes.n++
  const heredocs: { end: string; strip: boolean; into: string[] }[] = []
  const endWord = () => {
    if (!has) return
    if (route === 'arg') words.push(word)
    else if (route === 'heredoc') heredocs.push({ end: word, strip, into: input })
    else if (route === 'herestring') input.push(word)
    route = 'arg'
    word = ''
    has = false
  }
  const endCommand = (piped: boolean) => {
    endWord()
    route = 'arg'
    if (words.length || input.length) out.push({ words, input, pipe })
    words = []
    input = []
    if (!piped) pipe = pipes.n++
  }
  const bodies = () => { // after a line's end: the here-documents it began, each up to its own end line
    for (const doc of heredocs.splice(0)) {
      const lines: string[] = []
      while (at.i < source.length) {
        const end = source.indexOf('\n', at.i)
        const line = source.slice(at.i, end < 0 ? source.length : end)
        at.i = end < 0 ? source.length : end + 1
        if ((doc.strip ? line.replace(/^\t+/, '') : line) === doc.end) break
        lines.push(line)
      }
      doc.into.push(lines.join('\n'))
    }
  }
  const substitution = (close: string) => { // `$( … )` or a backquote's: commands of their own
    parse(source, at, close, out, pipes)
    word += close === ')' ? '$()' : '``'
    has = true
  }
  const quoted = () => { // "…": a backslash keeps only $ ` " \ and a newline; $( … ) and backquotes still run
    while (at.i < source.length) {
      const c = source[at.i]
      if (c === '"') {
        at.i++
        return
      }
      if (c === '\\' && '$`"\\\n'.includes(source[at.i + 1] ?? 'x')) {
        if (source[at.i + 1] !== '\n') word += source[at.i + 1]
        at.i += 2
      } else if (c === '$' && source[at.i + 1] === '(') {
        at.i += 2
        substitution(')')
      } else if (c === '`') {
        at.i++
        substitution('`')
      } else {
        word += c
        at.i++
      }
    }
  }
  while (at.i < source.length) {
    const c = source[at.i]
    const next = source[at.i + 1]
    if (stop === '`' && c === '`') {
      at.i++
      break
    }
    if (c === '\\') {
      if (next !== '\n') {
        word += next ?? ''
        has = true
      }
      at.i += 2
    } else if (c === "'") {
      const end = source.indexOf("'", at.i + 1)
      word += source.slice(at.i + 1, end < 0 ? source.length : end)
      has = true
      at.i = end < 0 ? source.length : end + 1
    } else if (c === '"') {
      at.i++
      has = true
      quoted()
    } else if (c === '$' && next === '(') {
      at.i += 2
      substitution(')')
    } else if (c === '`') {
      at.i++
      substitution('`')
    } else if ((c === '<' || c === '>') && next === '(') { // <( … ): a command, its output a file
      endWord()
      at.i += 2
      parse(source, at, ')', out, pipes)
    } else if (c === '#' && !has) { // a comment, to the line's end
      const end = source.indexOf('\n', at.i)
      at.i = end < 0 ? source.length : end
    } else if (c === ' ' || c === '\t') {
      endWord()
      at.i++
    } else if (c === '\n') {
      endCommand(false)
      at.i++
      bodies()
    } else if (c === '&' && next === '>') { // &> and &>>: both outputs to a file
      endWord()
      route = 'file'
      at.i += source[at.i + 2] === '>' ? 3 : 2
    } else if (c === ';' || c === '&' || c === '|') {
      endCommand(c === '|' && next !== '|') // `|` and `|&` go on in the same pipeline
      at.i += (c === '&' && next === '&') || (c === '|' && (next === '|' || next === '&')) ||
              (c === ';' && (next === ';' || next === '&')) ? 2 : 1 // (&&, ||, |&, ;;, ;&)
    } else if (c === '(') {
      endCommand(false)
      depth++
      at.i++
    } else if (c === ')') {
      at.i++
      if (depth === 0 && stop === ')') break
      endCommand(false)
      depth = Math.max(0, depth - 1)
    } else if (c === '<' || c === '>') { // a redirection: a word of digits before it is its descriptor
      if (has && route === 'arg' && /^\d+$/.test(word)) {
        word = ''
        has = false
      } else {
        endWord()
      }
      let op = c
      at.i++
      while (at.i < source.length && op.length < 3 && '<>&|-'.includes(source[at.i])) op += source[at.i++]
      route = op === '<<' || op === '<<-' ? 'heredoc' : op === '<<<' ? 'herestring' : 'file'
      strip = op === '<<-'
    } else {
      word += c
      has = true
      at.i++
    }
  }
  endCommand(false)
}
