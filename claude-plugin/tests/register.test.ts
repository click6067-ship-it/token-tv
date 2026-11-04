import { expect, mock, test } from 'claude-code/testing'

// A fake computer for the mod: a TokenTV state folder, a running TokenTV (or none) and Claude Code's own answers.
// What the mod sends is caught at $.http.fetch; nothing leaves the test.
const HOME = '/home/user'
const STATE = HOME + '/.config/token-tv/state'
const flush = () => new Promise((done) => setTimeout(done, 25))
const DRAWN = { type: 'Text', props: {}, children: ['Bash(rm -rf build)'] }

function computer(on: any, options: any = {}) {
  const files: Record<string, string> = options.files ?? { [STATE + '/live.url']: 'http://127.0.0.1:8791' }
  const stamps: Record<string, number> = options.stamps ?? {} // when each file was written (TokenTV's run)
  const sockets: string[] = options.sockets ?? [STATE + '/live.sock']
  const sent: any[] = []
  const gates: Record<string, () => void> = {}
  const verdicts: Record<string, any> = options.verdicts ?? {}
  mock.env(on, options.env ?? { HOME })
  // the kit hands paths over made absolute (a Windows path, here on another system, comes prefixed): by their end
  const find = (path: string) => Object.keys(files).find((name) => path === name || path.endsWith('/' + name))
  const socket = (path: string) => sockets.some((name) => path === name || path.endsWith('/' + name))
  const reads: string[] = []
  on('fs.read', ($: any, e: any) => {
    reads.push(e.path)
    return find(e.path) ? { value: files[find(e.path)!] } : { deny: 'ENOENT: no such file' }
  })
  on('fs.exists', ($: any, e: any) => ({ value: socket(e.path) || Boolean(find(e.path)) }))
  on('fs.stat', ($: any, e: any) => {
    const name = find(e.path)
    return name ? { value: { kind: 'file', size: files[name].length, mtimeMs: stamps[name] ?? 1, isLink: false } }
      : { deny: 'ENOENT: no such file' }
  })
  // the session's folder as Claude Code says it (`$.session.root()`, absolute; the kit has none of its own)
  const root = 'root' in options ? options.root : '/work'
  on('session.root', () => (root ? { value: root } : { deny: 'no folder' }))
  const refused: any[] = []
  on('http.fetch', options.fetch ?? (($: any, e: any) => {
    if (e.init?.socketPath !== undefined && !/^\//.test(e.init.socketPath)) { // as Claude Code 2.1.289 refuses it
      refused.push(e)
      return { deny: 'socketPath takes an absolute path' }
    }
    sent.push(e)
    return { value: { status: 204, ok: true, headers: {}, text: '' } }
  }))
  const calls: any[] = []
  // Claude Code itself: a call waits inside next() for the check, the person and the tool, here until released
  on('tool.call', async ($: any, e: any) => {
    calls.push(e)
    await new Promise<void>((done) => { gates[e.tool_use_id] = done })
    return { result: 'ran ' + e.tool_use_id, context: ['for the model'] }
  })
  on('tool.check', ($: any, e: any) => verdicts[e.tool_use_id] ?? { decision: 'ask' })
  on('ui.render', ($: any, e: any) => DRAWN) // Claude Code's own drawing of the row
  on('turn.complete', () => ({ text: '' }))
  on('session.start', () => ({ cwd: '/work' }))
  on('session.end', () => ({ sessionId: 'session' }))
  on('classic.SessionStart', () => ({}))
  const registered: any[] = [] // the slash commands the mod offers, as Claude Code is asked to list them
  on('command.register', ($: any, e: any) => {
    registered.push(e)
    return { value: { command: e.name } }
  })
  return { sent, refused, calls, reads, registered, release: (id: string) => gates[id]?.(),
           moments: () => sent.map((s) => JSON.parse(s.init.body).moment) }
}

// A slash command as Claude Code runs it once the person typed `/tokentv <args>` (the words after the name in
// `args`; left out for a bare `/tokentv`, as the kit does).
const tokentv = ($: any, args?: string) => $.command.run(args === undefined ? { command: 'tokentv' } : { command: 'tokentv', args })

// Claude Code drawing tool calls' rows, as it does the moment you answer a prompt: a ToolGroup with its calls in a
// list, or a ToolUse row of one call (measured in 2.1.289: the asked call `isRunning` once you said yes).
const row = (id: string, fields: any = {}) => ({ tool_use_id: id, tool: 'Bash', input: { command: 'rm -rf build' },
                                                 isRunning: false, isErrored: false, isInterrupted: false, ...fields })
const group = ($: any, ...calls: any[]) => $.ui.render({ surface: 'terminal', component: 'ToolGroup', requestId: 'g1',
                                                          props: { calls, isActive: true, isExpanded: false } })
const single = ($: any, call: any) => $.ui.render({ surface: 'terminal', component: 'ToolUse', requestId: call.tool_use_id,
                                                     props: call })

// A tool call that needs your permission: the call starts, Claude Code checks it, and the prompt waits for you.
async function prompt($: any, id: string, command = 'rm -rf build') {
  const call = $.tool.call({ tool: 'Bash', command, tool_use_id: id })
  call.catch(() => {}) // a call a test leaves waiting is let go with the test, not left a rejection nobody handles
  await flush()
  const verdict = await $.tool.check({ tool: 'Bash', input: { command }, tool_use_id: id })
  await flush()
  return { call, verdict }
}

const turn = (turnId: string, extra: any = {}) =>
  ({ turnId, answer: 'done', durationMs: 1200, isAborted: false, usage: null, ...extra })

test('a permission prompt is one claude.ask, and the end of that call is claude.answered', async ($: any, on: any) => {
  const pc = computer(on)
  const { call, verdict } = await prompt($, 't1')
  expect(verdict).toEqual({ decision: 'ask' }) // Claude Code's verdict passes on untouched
  expect(pc.moments()).toEqual(['claude.ask'])
  pc.release('t1') // you answered and the tool ran
  expect(await call).toEqual({ result: 'ran t1', context: ['for the model'] })
  await flush()
  expect(pc.moments()).toEqual(['claude.ask', 'claude.answered'])
  expect(pc.sent[0].url).toBe('http://127.0.0.1:8791/moment')
  expect(pc.sent[0].init).toEqual({
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: '{"moment":"claude.ask"}',
    socketPath: STATE + '/live.sock',
  })
})

test('the hand comes down as you answer: the asked call drawn running, long before the tool is done',
  async ($: any, on: any) => {
    const pc = computer(on)
    const { call } = await prompt($, 'y1')
    const done = row('d1', { output: { stdout: '' } }) // a call before it, over already
    expect(await group($, done, row('y1'))).toEqual(DRAWN) // the dialog is up: not answered yet
    await flush()
    expect(pc.moments()).toEqual(['claude.ask'])
    expect(await group($, done, row('y1', { isRunning: true }))).toEqual(DRAWN) // "Yes": drawn untouched
    await flush()
    expect(pc.moments()).toEqual(['claude.ask', 'claude.answered'])
    expect(await Promise.race([call, flush().then(() => 'still running')])).toBe('still running') // the tool runs on
    await single($, row('y1', { isRunning: true }))
    pc.release('y1')
    await call
    await flush()
    expect(pc.moments()).toEqual(['claude.ask', 'claude.answered']) // once, however often drawn, not again at its end
  })

test('a "No" closes the prompt when its refusal is drawn, or else when the call ends', async ($: any, on: any) => {
  const pc = computer(on)
  const first = await prompt($, 'n1')
  await single($, row('n1', { isErrored: true, output: 'The user refused this tool use' }))
  await flush()
  expect(pc.moments()).toEqual(['claude.ask', 'claude.answered'])
  pc.release('n1')
  await first.call
  const second = await prompt($, 'n2')
  await group($, row('n2')) // drawn while the dialog is up, and never again
  await flush()
  expect(pc.moments()).toEqual(['claude.ask', 'claude.answered', 'claude.ask'])
  pc.release('n2') // refused: the call ends with no tool run
  await second.call
  await flush()
  expect(pc.moments()).toEqual(['claude.ask', 'claude.answered', 'claude.ask', 'claude.answered'])
})

test('a drawing of another call, or of any call with no prompt open, answers nothing and is drawn untouched',
  async ($: any, on: any) => {
    const pc = computer(on)
    expect(await group($, row('x1', { isRunning: true }), row('x2', { output: 'ok' }))).toEqual(DRAWN)
    expect(await single($, row('x3', { isRunning: true }))).toEqual(DRAWN)
    await flush()
    expect(pc.sent).toEqual([])
    const { call } = await prompt($, 'mine')
    expect(await group($, row('other', { isRunning: true }), row('mine'))).toEqual(DRAWN)
    await single($, row('another', { output: 'ok' }))
    await single($, row('mine', { output: null })) // waiting, its result none yet: no answer
    await flush()
    expect(pc.moments()).toEqual(['claude.ask'])
    pc.release('mine')
    await call
  })

test('no answer goes once TokenTV has let the wait go: the ask it joined began earlier there (TokenTV-Wait-Age)',
  async ($: any, on: any) => {
    const clock = mock.clock(on, { now: 1_000_000 })
    const ages: Record<string, string> = { late: '1500', fresh: '0' } // how long TokenTV's wait had lasted, in s
    let asked = ''
    const pc = computer(on, {
      fetch: ($: any, e: any) => {
        const ask = named(e) === 'claude.ask'
        pc.sent.push(e)
        return { value: { status: 204, ok: true, headers: ask ? { 'tokentv-wait-age': ages[asked] } : {}, text: '' } }
      },
    })
    asked = 'late' // another session's prompt had kept TokenTV waiting 25 minutes when this one joined
    const late = await prompt($, 'late')
    await clock.advance(8 * 60 * 1000) // TokenTV let the whole wait go 5 minutes ago
    await group($, row('late', { isRunning: true }))
    await flush()
    expect(pc.moments()).toEqual(['claude.ask'])
    asked = 'fresh' // a new wait, this prompt its first
    const fresh = await prompt($, 'fresh')
    await clock.advance(8 * 60 * 1000)
    await group($, row('fresh', { isRunning: true }))
    await flush()
    expect(pc.moments()).toEqual(['claude.ask', 'claude.ask', 'claude.answered'])
    pc.release('late')
    pc.release('fresh')
    await late.call
    await fresh.call
    await flush()
    expect(pc.moments()).toEqual(['claude.ask', 'claude.ask', 'claude.answered'])
  })

// (A verdict of `ask` with `decider: 'host'`, a hosted session's program to answer, sends nothing either; the test
// kit drops `decider` from a stubbed verdict, so only a real session shows it.)
test('calls nobody is asked about send nothing: allowed, denied, another mod\'s query', async ($: any, on: any) => {
    const pc = computer(on, {
      verdicts: {
        allowed: { decision: 'allow' },
        denied: { decision: 'deny', reason: 'rule' },
      },
    })
    for (const id of ['allowed', 'denied']) {
      const { call } = await prompt($, id)
      pc.release(id)
      await call
    }
    await $.tool.check({ tool: 'Bash', input: { command: 'ls' } }) // another mod's query: no call, no prompt
    await flush()
    expect(pc.moments()).toEqual([])
  })

test('nothing is asked of anyone in a -p run, in dontAsk mode, or by auto mode\'s classifier', async ($: any, on: any) => {
  const pc = computer(on)
  await $.session.start({ surface: null, isInteractive: false, cwd: '/work' })
  const first = await prompt($, 'p1')
  pc.release('p1')
  await first.call
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  for (const [mode, id] of [['dontAsk', 'd1'], ['auto', 'a1']]) {
    await $.classic.SessionStart({ hook_event_name: 'SessionStart', permission_mode: mode, source: 'startup' })
    const { call } = await prompt($, id)
    pc.release(id)
    await call
  }
  await flush()
  expect(pc.moments()).toEqual([])
})

test('in auto mode an ask rule still puts the prompt to you', async ($: any, on: any) => {
  const pc = computer(on, { verdicts: { r1: { decision: 'ask', rule: 'Bash(git push:*)' } } })
  await $.classic.SessionStart({ hook_event_name: 'SessionStart', permission_mode: 'auto', source: 'startup' })
  const { call } = await prompt($, 'r1', 'git push')
  expect(pc.moments()).toEqual(['claude.ask'])
  pc.release('r1')
  await call
  await flush()
  expect(pc.moments()).toEqual(['claude.ask', 'claude.answered'])
})

test('the same prompt seen again is still one wait, and one answer closes it; a late repeat opens nothing',
  async ($: any, on: any) => {
    const pc = computer(on)
    const { call } = await prompt($, 'same')
    for (let k = 0; k < 9; k++) await $.tool.check({ tool: 'Bash', input: { command: 'rm -rf build' }, tool_use_id: 'same' })
    await flush()
    expect(pc.moments()).toEqual(['claude.ask'])
    pc.release('same')
    await call
    await $.tool.check({ tool: 'Bash', input: { command: 'rm -rf build' }, tool_use_id: 'same' })
    await flush()
    expect(pc.moments()).toEqual(['claude.ask', 'claude.answered'])
  })

test('the end of a turn closes its open prompt, then bows; a turn cut short only closes it', async ($: any, on: any) => {
  const pc = computer(on)
  await prompt($, 'w1')
  await $.turn.complete(turn('turn-1'))
  await flush()
  expect(pc.moments()).toEqual(['claude.ask', 'claude.answered', 'claude.end'])
  await prompt($, 'w2')
  await $.turn.complete(turn('turn-2', { isAborted: true }))
  await $.turn.complete(turn('turn-1')) // the same turn seen again: no second bow
  await flush()
  expect(pc.moments()).toEqual(['claude.ask', 'claude.answered', 'claude.end', 'claude.ask', 'claude.answered'])
})

test('a subagent\'s turn closes only its own prompts and is no bow', async ($: any, on: any) => {
  const pc = computer(on, { verdicts: {} })
  const main = await prompt($, 'main-1')
  // the subagent's own prompt
  const sub = $.tool.call({ tool: 'Bash', command: 'make', tool_use_id: 'sub-1', agentId: 'agent-7' })
  await flush()
  await $.tool.check({ tool: 'Bash', input: { command: 'make' }, tool_use_id: 'sub-1', agentId: 'agent-7' })
  await flush()
  await $.turn.complete(turn('sub-turn', { agentId: 'agent-7' }))
  await flush()
  expect(pc.moments()).toEqual(['claude.ask', 'claude.ask', 'claude.answered'])
  pc.release('main-1')
  pc.release('sub-1')
  await main.call
  await sub
  await flush()
  expect(pc.moments()).toEqual(['claude.ask', 'claude.ask', 'claude.answered', 'claude.answered'])
})

test('closing the session closes its open prompts', async ($: any, on: any) => {
  const pc = computer(on)
  await prompt($, 'x1')
  await prompt($, 'x2')
  await $.session.end({ reason: 'prompt_input_exit' })
  await flush()
  expect(pc.moments()).toEqual(['claude.ask', 'claude.ask', 'claude.answered', 'claude.answered'])
})

test('an answer at or after the time TokenTV lets the wait go (30 minutes) is not sent', async ($: any, on: any) => {
  const clock = mock.clock(on, { now: 1_000_000 })
  const pc = computer(on)
  const { call } = await prompt($, 'old')
  await clock.advance(30 * 60 * 1000 - 5000) // five seconds before: it could land just after TokenTV let go
  pc.release('old')
  await call
  await flush()
  expect(pc.moments()).toEqual(['claude.ask'])
})

test('no TokenTV running: nothing is sent, and Claude Code goes on as before', async ($: any, on: any) => {
  const pc = computer(on, { files: {}, sockets: [] })
  const { call, verdict } = await prompt($, 'n1')
  pc.release('n1')
  expect(await call).toEqual({ result: 'ran n1', context: ['for the model'] })
  expect(verdict).toEqual({ decision: 'ask' })
  await $.turn.complete(turn('t'))
  await flush()
  expect(pc.sent).toEqual([])
})

test('only this computer\'s loopback address, over TokenTV\'s socket; anything else in live.url sends nothing',
  async ($: any, on: any) => {
    const files: Record<string, string> = {}
    const pc = computer(on, { files })
    const bad = ['http://example.com:8787', 'http://192.0.2.7:8787', 'http://user@127.0.0.1:8787',
      'http://127.0.0.1@evil.example:8787', 'http://localhost.evil.example:8787', 'https://127.0.0.1:8787',
      'http://127.0.0.1:8787/moment', 'http://127.0.0.1:99999', 'http://127.0.0.1']
    for (const url of bad) {
      files[STATE + '/live.url'] = url
      await $.turn.complete(turn(url))
      await flush()
    }
    expect(pc.sent).toEqual([])
    for (const [url, to] of [['http://localhost:8790', 'http://127.0.0.1:8790/moment'],
                             ['http://[::1]:8792', 'http://[::1]:8792/moment'], ['http://127.0.0.1:8793\n', 'http://127.0.0.1:8793/moment']]) {
      files[STATE + '/live.url'] = url
      await $.turn.complete(turn('ok ' + url))
      await flush()
      expect([pc.sent.at(-1).url, pc.sent.at(-1).init.socketPath]).toEqual([to, STATE + '/live.sock'])
    }
  })

test('nothing goes anywhere but TokenTV\'s socket: a live.url alone sends nothing', async ($: any, on: any) => {
  const pc = computer(on, { sockets: [] }) // live.url left by a TokenTV that stopped, its port maybe another's now
  await prompt($, 'p1')
  await $.turn.complete(turn('t'))
  await flush()
  expect(pc.sent).toEqual([])
})

const PLACES = { '/xdg/token-tv/state/live.url': 'http://127.0.0.1:8801', '/srv/tv/state/live.url': 'http://127.0.0.1:8802',
                 [HOME + '/tv2/state/live.url']: 'http://127.0.0.1:8803' }

const SOCKETS = ['/xdg/token-tv/state/live.sock', '/srv/tv/state/live.sock', HOME + '/tv2/state/live.sock']

for (const [env, url, socket] of [
  [{ HOME, XDG_CONFIG_HOME: '/xdg' }, 'http://127.0.0.1:8801/moment', '/xdg/token-tv/state/live.sock'],
  [{ HOME, XDG_CONFIG_HOME: '/xdg', TOKEN_TV_CONFIG: '/srv/tv/config.json' }, 'http://127.0.0.1:8802/moment', '/srv/tv/state/live.sock'],
  [{ HOME, TOKEN_TV_CONFIG: '~/tv2/config.json' }, 'http://127.0.0.1:8803/moment', HOME + '/tv2/state/live.sock'],
] as const) {
  test(`TokenTV is found where it runs (${Object.keys(env).join(', ')})`, async ($: any, on: any) => {
    const pc = computer(on, { env, files: PLACES, sockets: SOCKETS })
    await $.turn.complete(turn('a'))
    await flush()
    expect(pc.sent.map((s) => [s.url, s.init.socketPath])).toEqual([[url, socket]])
  })
}

// A relative TOKEN_TV_CONFIG: its state folder is in the folder the session started in, and the socket goes by its
// absolute path (Claude Code 2.1.289 refuses a relative one, as the fake host here does).
for (const [config, folder] of [['config.json', '/work/project/state'], ['./config.json', '/work/project/state'],
                                ['tv/config.json', '/work/project/tv/state']] as const) {
  test(`TOKEN_TV_CONFIG=${config} is found beside it in the session's folder, by an absolute path`, async ($: any, on: any) => {
    const pc = computer(on, { env: { HOME, TOKEN_TV_CONFIG: config }, root: '/work/project',
                              files: { [folder + '/live.url']: 'http://127.0.0.1:8806' }, sockets: [folder + '/live.sock'] })
    await prompt($, 'c1')
    await $.turn.complete(turn('c'))
    await flush()
    expect(pc.reads.filter((path: string) => path.includes('config.json'))).toEqual([])
    expect(pc.refused).toEqual([])
    expect(pc.sent.map((s) => [s.url, s.init.socketPath])).toEqual([
      ['http://127.0.0.1:8806/moment', folder + '/live.sock'], ['http://127.0.0.1:8806/moment', folder + '/live.sock'],
      ['http://127.0.0.1:8806/moment', folder + '/live.sock']])
    expect(pc.moments()).toEqual(['claude.ask', 'claude.answered', 'claude.end'])
  })
}

for (const [label, root] of [['none', null], ['a relative one', 'work/project']] as const) {
  test(`a relative TOKEN_TV_CONFIG with no absolute folder for the session (${label}) sends nothing`, async ($: any, on: any) => {
    // (a TokenTV beside it wherever the kit looks, so only the rule keeps the moment back)
    const pc = computer(on, { env: { HOME, TOKEN_TV_CONFIG: 'config.json' }, root,
                              files: { 'state/live.url': 'http://127.0.0.1:8806' }, sockets: ['state/live.sock'] })
    await prompt($, 'c1')
    await $.turn.complete(turn('c'))
    await flush()
    expect(pc.sent).toEqual([])
    expect(pc.refused).toEqual([])
  })
}

// Windows: nothing for now. TokenTV makes no socket there, and over TCP Claude Code's fetch takes a proxy set in its
// environment and follows a redirect wherever it points, whatever its options say (2.1.289, measured): a moment's
// name could leave this computer. Whatever the environment and the files say, nothing is sent; off Windows the same
// folders are found and the moments go, so it is Windows alone that keeps them back.
const PROXY = 'http://proxy.example:3128'
const EVERYWHERE = { ...PLACES, [HOME + '/.config/token-tv/state/live.url']: 'http://127.0.0.1:8804',
                     'C:/Users/u/.config/token-tv/state/live.url': 'http://127.0.0.1:8805',
                     'C:\\work/tv\\state/live.url': 'http://127.0.0.1:8806' }
const BESIDE = Object.keys(EVERYWHERE).map((url) => url.replace(/live\.url$/, 'live.sock')) // a socket by each

for (const [label, env] of [
  ['the folder token-tv start uses', {}],
  ['HOME', { HOME }],
  ['XDG_CONFIG_HOME', { HOME, XDG_CONFIG_HOME: '/xdg' }],
  ['an absolute TOKEN_TV_CONFIG', { TOKEN_TV_CONFIG: '/srv/tv/config.json' }],
  ['a relative TOKEN_TV_CONFIG', { TOKEN_TV_CONFIG: 'tv\\config.json' }],
  ['NO_PROXY=127.0.0.1', { HTTP_PROXY: PROXY, NO_PROXY: '127.0.0.1' }],
  ['NO_PROXY=*', { ALL_PROXY: PROXY, no_proxy: '*' }],
] as const) {
  for (const windows of [true, false]) {
    const name = windows ? 'on Windows nothing is sent, whatever the environment and the files say'
      : 'off Windows the same folders are found and the moments go'
    test(`${name} (${label})`, async ($: any, on: any) => {
      const fetched: any[] = []
      const pc = computer(on, { env: { USERPROFILE: 'C:/Users/u', ...(windows ? { OS: 'Windows_NT' } : {}), ...env },
                                root: 'C:\\work', files: EVERYWHERE, sockets: BESIDE, fetch: ($: any, e: any) => {
                                  fetched.push(e) // whatever it is: a moment, a check, to a socket or a port
                                  return { value: { status: 204, ok: true, headers: {}, text: '' } }
                                } })
      const { call } = await prompt($, 'w1')
      await group($, row('w1', { isRunning: true }))
      pc.release('w1')
      await call
      await $.turn.complete(turn('w'))
      await prompt($, 'w2')
      await $.session.end({ reason: 'prompt_input_exit' })
      await flush()
      expect(fetched.map((e) => (e.init?.body ? named(e) : 'a request naming no moment'))).toEqual(windows ? []
        : ['claude.ask', 'claude.answered', 'claude.end', 'claude.ask', 'claude.answered'])
    })
  }
}

test('on Windows nothing goes to TokenTV\'s port either, whatever answers there', async ($: any, on: any) => {
  // the folder as TokenTV leaves it on Windows (live.url, no socket), and on the port a server that answers any
  // check as TokenTV once did (405, `TokenTV: moments`) and takes any moment
  const fetched: any[] = []
  computer(on, { env: { USERPROFILE: 'C:/Users/u', OS: 'Windows_NT' }, files: EVERYWHERE, sockets: [],
                 fetch: ($: any, e: any) => {
                   fetched.push(e)
                   return { value: e.init?.method === 'POST' ? { status: 204, ok: true, headers: {}, text: '' }
                     : { status: 405, ok: false, headers: { allow: 'POST', tokentv: 'moments' }, text: '' } }
                 } })
  await prompt($, 'w1')
  await $.turn.complete(turn('w'))
  await flush()
  expect(fetched).toEqual([])
})

const named = (e: any) => JSON.parse(e.init.body).moment

test('a TokenTV that never answers holds nothing up; what it held back past five seconds is dropped, new ones go',
  async ($: any, on: any) => {
    const clock = mock.clock(on, { now: 1_000_000 })
    const tried: string[] = []
    let hang = true
    computer(on, {
      fetch: async ($: any, e: any) => {
        tried.push(named(e))
        if (hang) await clock.sleep(60_000) // longer than any call waits for
        return { value: { status: 204, ok: true, headers: {}, text: '' } }
      },
    })
    const started = Date.now()
    await prompt($, 'h1')
    for (const id of ['a', 'b']) await $.turn.complete(turn(id)) // closes h1, then two ends
    await flush()
    expect(Date.now() - started).toBeLessThan(1000) // the hooks never waited for a send
    expect(tried).toEqual(['claude.ask']) // the next waits for an answer, two seconds at most
    for (let k = 0; k < 5; k++) {
      await clock.advance(2000)
      await flush()
    }
    // h1's answer waited five seconds for TokenTV to confirm the ask, in vain: not sent. The ends, held up past
    // five seconds by then, are dropped rather than sent late.
    expect(tried).toEqual(['claude.ask'])
    hang = false // TokenTV answers again (another one started, say): a new moment goes at once
    await $.turn.complete(turn('c'))
    await flush()
    expect(tried).toEqual(['claude.ask', 'claude.end'])
  })

test('an answer whose ask TokenTV confirmed late still goes', async ($: any, on: any) => {
  const clock = mock.clock(on, { now: 1_000_000 })
  const tried: string[] = []
  computer(on, {
    fetch: async ($: any, e: any) => {
      tried.push(named(e))
      if (named(e) === 'claude.ask') await clock.sleep(3000) // slower than the two seconds the queue waits
      return { value: { status: 204, ok: true, headers: {}, text: '' } }
    },
  })
  await prompt($, 'late')
  await $.turn.complete(turn('l', { isAborted: true })) // closes the prompt, no bow
  await flush()
  await clock.advance(2000)
  await flush()
  expect(tried).toEqual(['claude.ask']) // the answer waits for the ask's own answer
  await clock.advance(1000)
  await flush()
  expect(tried).toEqual(['claude.ask', 'claude.answered'])
})

test('each moment waits for the one before it to be answered, so TokenTV takes them in order', async ($: any, on: any) => {
  const clock = mock.clock(on, { now: 1_000_000 })
  const tried: string[] = []
  const pc = computer(on, {
    fetch: async ($: any, e: any) => {
      tried.push(named(e))
      await clock.sleep(400)
      return { value: { status: 204, ok: true, headers: {}, text: '' } }
    },
  })
  await prompt($, 'o1')
  await $.turn.complete(turn('o')) // its answer and its end, right after one another
  await flush()
  expect(tried).toEqual(['claude.ask'])
  await clock.advance(400)
  await flush()
  expect(tried).toEqual(['claude.ask', 'claude.answered'])
  await clock.advance(400)
  await flush()
  expect(tried).toEqual(['claude.ask', 'claude.answered', 'claude.end'])
  pc.release('o1')
})

test('an answer goes only to the TokenTV that counted its ask, not to one started since', async ($: any, on: any) => {
  const stamps: Record<string, number> = { [STATE + '/live.url']: 111 }
  const pc = computer(on, { stamps })
  const { call } = await prompt($, 'r1')
  stamps[STATE + '/live.url'] = 222 // TokenTV restarted: it never saw that ask
  pc.release('r1')
  await call
  await $.turn.complete(turn('r'))
  await flush()
  expect(pc.moments()).toEqual(['claude.ask', 'claude.end'])
})

test('a failing TokenTV is quiet: the hooks go on, each moment is tried once, and an ask it never took is not answered',
  async ($: any, on: any) => {
    const tried: string[] = []
    computer(on, { fetch: ($: any, e: any) => { tried.push(named(e)); return { deny: 'connection refused' } } })
    const { call } = await prompt($, 'f1')
    await $.turn.complete(turn('f'))
    await flush()
    expect(tried).toEqual(['claude.ask', 'claude.end'])
  })

test('prompts, commands, paths, outputs and ids never leave the mod', async ($: any, on: any) => {
  const pc = computer(on)
  const canaries = ['CANARY-PROMPT-7f3', 'CANARY-CMD-91c', 'CANARY-PATH-2ab', 'CANARY-SESSION-5d0', 'CANARY-OUT-e44',
    'CANARY-TOOLID-0c1', 'CANARY-TURN-b77', 'CANARY-AGENT-3f9']
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work/CANARY-PATH-2ab' })
  await $.classic.SessionStart({ hook_event_name: 'SessionStart', session_id: 'CANARY-SESSION-5d0', permission_mode: 'default',
    cwd: '/work/CANARY-PATH-2ab', transcript_path: '/work/CANARY-PATH-2ab/t.jsonl', source: 'startup' })
  const call = $.tool.call({ tool: 'Bash', command: 'cat /work/CANARY-PATH-2ab # CANARY-CMD-91c', tool_use_id: 'CANARY-TOOLID-0c1',
    agentId: 'CANARY-AGENT-3f9' })
  await flush()
  await $.tool.check({ tool: 'Bash', input: { command: 'CANARY-CMD-91c', file_path: '/work/CANARY-PATH-2ab' },
    tool_use_id: 'CANARY-TOOLID-0c1', agentId: 'CANARY-AGENT-3f9' })
  pc.release('CANARY-TOOLID-0c1')
  await call
  await $.turn.complete(turn('CANARY-TURN-b77', { answer: 'CANARY-OUT-e44 CANARY-PROMPT-7f3' }))
  await flush()
  expect(pc.moments()).toEqual(['claude.ask', 'claude.answered', 'claude.end'])
  const everything = JSON.stringify(pc.sent)
  for (const canary of canaries) expect(everything).not.toContain(canary)
  for (const one of pc.sent) {
    expect(Object.keys(JSON.parse(one.init.body))).toEqual(['moment'])
    expect(Object.keys(one.init.headers)).toEqual(['content-type'])
  }
})

test('the call, its arguments and its result pass through untouched, and only you answer the prompt',
  async ($: any, on: any) => {
    const pc = computer(on)
    const { call } = await prompt($, 'u1', 'echo "untouched" && ls -la')
    expect(await Promise.race([call, flush().then(() => 'still waiting')])).toBe('still waiting')
    expect(pc.calls).toEqual([{ tool: 'Bash', command: 'echo "untouched" && ls -la', tool_use_id: 'u1' }])
    pc.release('u1')
    expect(await call).toEqual({ result: 'ran u1', context: ['for the model'] })
  })

test('a subagent\'s prompt is its own even when the check does not say whose it is', async ($: any, on: any) => {
  const pc = computer(on)
  const sub = $.tool.call({ tool: 'Bash', command: 'make', tool_use_id: 's1', agentId: 'agent-9' })
  await flush()
  await $.tool.check({ tool: 'Bash', input: { command: 'make' }, tool_use_id: 's1' }) // Claude Code 2.1.289
  await $.turn.complete(turn('main-turn')) // the main turn's end leaves the subagent's prompt open
  await flush()
  expect(pc.moments()).toEqual(['claude.ask', 'claude.end'])
  await $.turn.complete(turn('sub-turn', { agentId: 'agent-9' }))
  await flush()
  expect(pc.moments()).toEqual(['claude.ask', 'claude.end', 'claude.answered'])
  pc.release('s1')
  await sub
})

// --- /tokentv pet and /tokentv snack (e5) ----------------------------------------------------------------------------

test('/tokentv is one slash command, offered as the session starts, running at once mid-turn', async ($: any, on: any) => {
  const pc = computer(on)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  expect(pc.registered).toEqual([{ name: 'tokentv', description: 'Pet Clawd on your TokenTV clock, or give it a snack',
                                   argumentHint: 'pet | snack', immediate: true }])
  expect(pc.sent).toEqual([]) // offering it sends nothing
})

test('/tokentv pet and /tokentv snack each send their one name, and only that', async ($: any, on: any) => {
  const pc = computer(on)
  expect(await tokentv($, 'pet')).toEqual({ text: 'A pat for Clawd, on its way to TokenTV.' })
  await flush()
  expect(pc.moments()).toEqual(['claude.pet'])
  expect(pc.sent[0].url).toBe('http://127.0.0.1:8791/moment')
  expect(pc.sent[0].init).toEqual({ method: 'POST', headers: { 'content-type': 'application/json' },
                                    body: '{"moment":"claude.pet"}', socketPath: STATE + '/live.sock' })
  expect(await tokentv($, '  Snack ')).toEqual({ text: 'A snack for Clawd, on its way to TokenTV.' })
  await flush()
  expect(pc.moments()).toEqual(['claude.pet', 'claude.snack'])
  expect(pc.sent[1].init.body).toBe('{"moment":"claude.snack"}')
})

test('anything else after /tokentv sends nothing, and its words go nowhere', async ($: any, on: any) => {
  const pc = computer(on)
  const words = [undefined, '', 'pet CANARY-ARG-1a', 'snack now CANARY-ARG-2b', 'CANARY-ARG-3c', 'petting', 'pet\nsnack',
    'claude.pet', 'claude.ask', '{"moment":"claude.ask"}', 'constructor', '__proto__', 'toString', 'pet snack']
  for (const args of words) {
    expect(await tokentv($, args)).toEqual({ text: 'Try /tokentv pet or /tokentv snack.' })
  }
  await flush()
  expect(pc.sent).toEqual([])
  expect(pc.reads).toEqual([]) // not even a look for TokenTV
  await tokentv($, 'pet') // and the command still works
  await flush()
  expect(pc.moments()).toEqual(['claude.pet'])
  expect(JSON.stringify(pc.sent)).not.toContain('CANARY')
})

test('the session\'s prompts, paths and ids never leave with a pat or a snack', async ($: any, on: any) => {
  const pc = computer(on)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work/CANARY-PATH-6e1' })
  await $.classic.SessionStart({ hook_event_name: 'SessionStart', session_id: 'CANARY-SESSION-1f2', permission_mode: 'default',
    cwd: '/work/CANARY-PATH-6e1', transcript_path: '/work/CANARY-PATH-6e1/t.jsonl', source: 'startup' })
  await tokentv($, 'pet')
  await tokentv($, 'snack')
  await $.turn.complete(turn('CANARY-TURN-9a0', { answer: 'CANARY-OUT-4d2 CANARY-PROMPT-3c3' }))
  await flush()
  expect(pc.moments()).toEqual(['claude.pet', 'claude.snack', 'claude.end'])
  for (const one of pc.sent) {
    expect(Object.keys(JSON.parse(one.init.body))).toEqual(['moment'])
    expect(Object.keys(one.init.headers)).toEqual(['content-type'])
  }
  expect(JSON.stringify(pc.sent)).not.toContain('CANARY')
})

test('every press goes as it is made: TokenTV, not the mod, drops one while another is to show', async ($: any, on: any) => {
  const pc = computer(on)
  for (const args of ['pet', 'pet', 'snack', 'pet']) await tokentv($, args)
  await flush()
  expect(pc.moments()).toEqual(['claude.pet', 'claude.pet', 'claude.snack', 'claude.pet']) // in order, nothing added
})

for (const [label, options] of [['none at all', { files: {}, sockets: [] }], ['a live.url with no socket', { sockets: [] }]] as const) {
  test(`no TokenTV running (${label}): /tokentv sends nothing, and says so`, async ($: any, on: any) => {
    const pc = computer(on, options)
    expect(await tokentv($, 'pet')).toEqual({ text: 'No TokenTV is running on this computer: nothing was sent.' })
    await flush()
    expect(pc.sent).toEqual([])
  })
}

test('on Windows /tokentv sends nothing, and says so', async ($: any, on: any) => {
  const fetched: any[] = []
  computer(on, { env: { USERPROFILE: 'C:/Users/u', OS: 'Windows_NT' }, files: EVERYWHERE, sockets: BESIDE,
                 fetch: ($: any, e: any) => { fetched.push(e); return { value: { status: 204, ok: true, headers: {}, text: '' } } } })
  expect(await tokentv($, 'pet')).toEqual({ text: 'On Windows the TokenTV mod sends nothing for now.' })
  expect(await tokentv($, 'snack')).toEqual({ text: 'On Windows the TokenTV mod sends nothing for now.' })
  await flush()
  expect(fetched).toEqual([])
})

test('a pat never waits for TokenTV: one that hangs holds each press up two seconds at most, and one held past five is dropped',
  async ($: any, on: any) => {
    const clock = mock.clock(on, { now: 1_000_000 })
    const tried: string[] = []
    let hang = true
    computer(on, {
      fetch: async ($: any, e: any) => {
        tried.push(named(e))
        if (hang) await clock.sleep(60_000)
        return { value: { status: 204, ok: true, headers: {}, text: '' } }
      },
    })
    const started = Date.now()
    for (const args of ['pet', 'snack', 'pet', 'snack']) await tokentv($, args)
    expect(Date.now() - started).toBeLessThan(1000) // each command answered at once
    await flush()
    expect(tried).toEqual(['claude.pet']) // the next waits for its answer, two seconds at most
    await clock.advance(2000)
    await flush()
    expect(tried).toEqual(['claude.pet', 'claude.snack'])
    await clock.advance(2000)
    await flush()
    expect(tried).toEqual(['claude.pet', 'claude.snack', 'claude.pet'])
    await clock.advance(2000) // the last press is six seconds old by its turn: dropped, never sent late
    await flush()
    await clock.advance(2000)
    await flush()
    expect(tried).toEqual(['claude.pet', 'claude.snack', 'claude.pet'])
    hang = false // TokenTV answers again: a fresh press goes at once
    await tokentv($, 'snack')
    await flush()
    expect(tried).toEqual(['claude.pet', 'claude.snack', 'claude.pet', 'claude.snack'])
  })

test('a failing TokenTV is quiet: each press is tried once, and the next one still goes', async ($: any, on: any) => {
  const tried: string[] = []
  let refuse = true
  computer(on, { fetch: ($: any, e: any) => {
    tried.push(named(e))
    return refuse ? { deny: 'connection refused' } : { value: { status: 500, ok: false, headers: {}, text: '' } }
  } })
  await tokentv($, 'pet')
  await flush()
  refuse = false // now it answers, with an error
  await tokentv($, 'snack')
  await flush()
  expect(tried).toEqual(['claude.pet', 'claude.snack'])
})
