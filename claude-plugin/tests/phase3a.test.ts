import { expect, mock, test } from 'claude-code/testing'

// Phase 3a in the mod: the names a Bash command, a prompt, a failed tool, a compaction and the spinner's word bring,
// and the sounds. A fake computer as in register.test.ts: a TokenTV state folder with its socket, Claude Code's own
// answers (a call waits inside next() until the test settles it), and what the mod sends, caught at $.http.fetch.
const HOME = '/home/user'
const STATE = HOME + '/.config/token-tv/state'
const flush = () => new Promise((done) => setTimeout(done, 25))
const DRAWN = { type: 'Text', props: {}, children: ['drawn by Claude Code'] }

function computer(on: any, options: any = {}) {
  const files: Record<string, string> = options.files ?? { [STATE + '/live.url']: 'http://127.0.0.1:8791' }
  const sockets: string[] = options.sockets ?? [STATE + '/live.sock']
  const sent: any[] = []
  const gates: Record<string, (answer: any) => void> = {}
  const verdicts: Record<string, any> = options.verdicts ?? {}
  mock.env(on, options.env ?? { HOME })
  const find = (path: string) => Object.keys(files).find((name) => path === name || path.endsWith('/' + name))
  on('fs.read', ($: any, e: any) => (find(e.path) ? { value: files[find(e.path)!] } : { deny: 'ENOENT: no such file' }))
  on('fs.exists', ($: any, e: any) => ({ value: sockets.some((s) => e.path === s || e.path.endsWith('/' + s)) || Boolean(find(e.path)) }))
  on('fs.stat', ($: any, e: any) => (find(e.path) ? { value: { kind: 'file', size: 1, mtimeMs: 1, isLink: false } }
    : { deny: 'ENOENT: no such file' }))
  on('session.root', () => ({ value: '/work' }))
  on('http.fetch', options.fetch ?? (($: any, e: any) => {
    sent.push(e)
    return { value: { status: 204, ok: true, headers: {}, text: '' } }
  }))
  const calls: any[] = []
  const reached: number[] = [] // when each call reached Claude Code's own step (Date.now())
  const results: any[] = []
  on('tool.call', async ($: any, e: any) => { // Claude Code: the check, you and the tool, until the test settles it
    calls.push(e)
    reached.push(Date.now())
    const answer = await new Promise<any>((done) => { gates[e.tool_use_id] = done })
    return answer ?? { result: 'ran ' + e.tool_use_id }
  })
  on('tool.check', ($: any, e: any) => verdicts[e.tool_use_id] ?? { decision: 'allow' })
  // You, at the prompt Claude Code raises for a call whose check says ask (register.test.ts has it): here "Yes" at once.
  on('classic.PermissionRequest', () => ({ decision: { behavior: 'allow' } }))
  on('ui.render', ($: any, e: any) => DRAWN)
  on('turn.start', ($: any, e: any) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('prompt.submit', ($: any, e: any) => ({ text: e.text }))
  on('session.compact', ($: any, e: any) => (options.skip ? { skip: 'no' } : { messages: [{ role: 'user', text: 'summary', toolUses: [] }] }))
  on('session.start', () => ({ cwd: '/work' }))
  on('session.end', () => ({ sessionId: 'session' }))
  on('classic.SessionStart', () => ({}))
  on('classic.PostToolUseFailure', () => ({}))
  on('classic.PermissionDenied', () => ({}))
  on('command.register', () => ({ value: { command: 'tokentv' } }))
  const store: Record<string, unknown> = options.store ?? {}
  const writes: any[] = []
  if (options.store !== false) {
    on('store.get', ($: any, e: any) => ({ value: store[e.key] }))
    on('store.set', ($: any, e: any) => {
      writes.push([e.key, e.value])
      store[e.key] = e.value
      return { value: undefined }
    })
  }
  const plays: any[] = []
  on('audio.play', options.audio ?? (($: any, e: any) => {
    plays.push(e.clip)
    return { value: undefined }
  }))
  return {
    sent, calls, reached, results, plays, store, writes,
    settle: (id: string, answer?: any) => gates[id]?.(answer),
    moments: () => sent.map((s) => JSON.parse(s.init.body).moment),
  }
}

// A Bash call as Claude Code makes it, once Claude Code has it (the mod saw it start); the test settles it later.
async function bash($: any, pc: any, id: string, command: string) {
  return started($, pc, { tool: 'Bash', command, tool_use_id: id })
}
async function started($: any, pc: any, input: any) {
  const call = $.tool.call(input)
  call.catch(() => {}) // (a call a test leaves waiting is let go with the test)
  await until(() => pc.calls.some((c: any) => c.tool_use_id === input.tool_use_id))
  return { call }
}

const turn = (turnId: string, extra: any = {}) =>
  ({ turnId, answer: 'done', durationMs: 1200, isAborted: false, reason: 'answer', usage: null, ...extra })
// (the kit marks what is drawn with who drew it, `part`: left out, the test is about the tree)
const spinner = ($: any, word: unknown, extra: any = {}) =>
  $.ui.render({ surface: 'terminal', component: 'Spinner', requestId: 'main',
                props: { word, message: null, suffix: '…', mode: 'thinking', ...extra } })
    .then(({ part, ...drawn }: any) => drawn)
const typed = ($: any, text: string, kind = 'composer') => $.prompt.submit({ text, origin: { kind }, wait: false })
const named = (e: any) => JSON.parse(e.init.body).moment
// Until `count` requests have gone out (each waits for the one before it), or a second has gone by.
async function sent(pc: any, count: number) {
  await until(() => pc.sent.length >= count)
}
// Until `done()` holds, or a second has gone by (a busy computer: the host's own steps take their time).
async function until(done: () => boolean) {
  for (let k = 0; k < 40 && !done(); k++) await flush()
}

// --- e3: the courtroom ---------------------------------------------------------------------------------------------

const RISKY = [
  'rm -rf ./fixture-dir-CANARY-A1', 'git push --force origin fixture-CANARY-A2', 'git push -f origin fixture',
  'git reset --hard HEAD', 'git clean -fd', "psql -c 'DROP TABLE fixture_table'", 'mysql -e "DROP DATABASE fixture_db"',
  'mkfs /dev/fixture', 'dd if=fixture.img of=/dev/fixture', 'chmod -R 777 /',
  // the same commands as a shell would also run them
  'rm -fr ./x', 'rm -r -f ./x', 'rm --recursive --force ./x', 'rm -Rf ./x', 'sudo rm -rf /var/fixture',
  'sudo -u root rm -rf ./x', '/bin/rm -rf ./x', 'FOO=1 rm -rf ./x', 'env FOO=1 rm -rf ./x', 'cd build && rm -rf out',
  'ls; rm -rf ./x', 'true || rm -rf ./x', "bash -c 'rm -rf ./x'", 'sh -lc "git push --force"',
  'git -C repo push --force-with-lease origin main', 'git push -uf origin main', 'git clean -fdx', 'git clean -f -d',
  'mkfs.ext4 /dev/sdb1', 'timeout 10 rm -rf ./x', 'find . -name "*.o" | xargs rm -rf',
  'find . -type d -exec rm -rf {} +', 'echo $(rm -rf ./x)', 'echo "DROP TABLE t;" | psql', 'sqlite3 db.sqlite "drop table t"',
  "psql <<'SQL'\nDROP TABLE fixture;\nSQL", 'chmod --recursive 0777 /', 'time rm -rf ./x', 'nohup rm -rf ./x &',
  // SQL that drops, a string or a comment beside it; a string run as a statement; a force push by a `+refspec`
  'psql -c "SELECT \'x\'; DROP TABLE x"', 'psql -c "-- tidy up\nDROP TABLE x"', 'psql --command="DROP TABLE x"',
  'psql -c \'DROP TABLE "x"\'', "mysql -e 'DROP TABLE `x`'", "psql -c 'DO $$ BEGIN DROP TABLE x; END $$'",
  'mysql -e "PREPARE s FROM \'DROP TABLE x\'; EXECUTE s"', 'psql -c "/* old */ DROP DATABASE d"',
  'git push origin +main', 'git push origin +HEAD:refs/heads/main', 'git push origin main +dev',
  'toString -x; rm -rf ./x', // (a command named like an Object property hides nothing after it)
]
const NOT_RISKY = [
  'git push origin fixture', 'git reset --soft HEAD', 'git clean -n', 'git clean -fdn', 'git clean -f',
  'chmod 777 ./file', 'chmod -R 755 ./folder', 'chmod -R 777 ./folder', 'dd if=fixture.img of=./copy.img',
  "psql -c 'SELECT * FROM fixture'", "printf '%s' 'rm -rf ./x'", '# git push --force', 'ls # git push --force',
  'echo DROP TABLE fixture', 'mkfs_notes', 'myrm -rf ./x', 'rm -r ./x', 'rm -f ./x', 'rm -rf', 'git commit -m "rm -rf build"',
  "git commit -m \"$(cat <<'EOF'\nfix: no more git push --force\n1) rm -rf build is gone\nEOF\n)\"",
  "cat <<'EOF' > notes.md\nrm -rf /\nEOF", 'grep -r "git reset --hard" .', 'echo "chmod -R 777 /"', 'git log --grep=force',
  'git push --follow-tags origin main', 'npm run clean', "python3 -c 'import os'", 'echo mkfs /dev/sda',
  // DROP as data to a database client: in a string, a quoted name or a comment
  'psql -c "SELECT \'DROP TABLE fixture\';"', 'psql -c "SELECT 1; -- DROP TABLE x"',
  'psql -c "/* DROP TABLE x */ SELECT 1"',
  'mysql -e "SELECT 1 # DROP TABLE x"', "psql -c 'SELECT $$DROP TABLE x$$'", 'psql -c \'SELECT "DROP TABLE x" FROM t\'',
  "psql <<'SQL'\n-- DROP TABLE x\nSELECT 'DROP DATABASE y';\nSQL", 'echo "-- DROP TABLE x" | psql',
  'psql --command="SELECT \'DROP TABLE x\'"', "mysql -e \"INSERT INTO log VALUES ('it\\'s DROP TABLE x')\"",
  'git push origin :old-branch', 'git push origin main',
]

test('every risky command family says claude.risky as the call starts, and nothing of the command', async ($: any, on: any) => {
  const pc = computer(on)
  for (const [k, command] of RISKY.entries()) {
    const before = pc.sent.length
    const { call } = await bash($, pc, 'r' + k, command)
    await sent(pc, before + 1)
    expect([command, pc.moments().slice(-1)[0]]).toEqual([command, 'claude.risky']) // the call still running
    expect(await Promise.race([call, flush().then(() => 'running')])).toBe('running')
    pc.settle('r' + k, { isError: true, result: 'stopped by the test', text: 'stopped' })
    await call
  }
  await flush()
  expect(pc.moments().filter((m) => m === 'claude.risky').length).toBe(RISKY.length)
  expect(JSON.stringify(pc.sent)).not.toContain('CANARY')
  for (const one of pc.sent) expect(Object.keys(JSON.parse(one.init.body))).toEqual(['moment'])
})

test('near misses, mentions and data are no risky command', async ($: any, on: any) => {
  const pc = computer(on)
  for (const [k, command] of NOT_RISKY.entries()) {
    const { call } = await bash($, pc, 'n' + k, command)
    await flush()
    pc.settle('n' + k, { isError: true, result: 'stopped by the test', text: 'stopped' })
    await call
    await flush()
    expect([command, pc.moments().includes('claude.risky')]).toEqual([command, false])
  }
  // risky words only in a prompt, a path, an output or another tool's data
  await typed($, 'please do not run rm -rf / or git push --force')
  const { call: write } = await started($, pc, { tool: 'Write', file_path: '/work/rm -rf/x.md',
                                                  content: 'git reset --hard; DROP TABLE t', tool_use_id: 'w1' })
  await flush()
  pc.settle('w1', { result: 'git push --force printed this' })
  await write
  const { call: read } = await bash($, pc, 'o1', 'cat notes.md')
  await flush()
  pc.settle('o1', { result: 'rm -rf / and DROP DATABASE x, as output' })
  await read
  await flush()
  expect(pc.moments().includes('claude.risky')).toBe(false)
  const { call: fresh } = await bash($, pc, 'p1', 'git reset --hard HEAD~1') // and a real one still says so
  await flush()
  expect(pc.moments().slice(-1)).toEqual(['claude.risky'])
  pc.settle('p1')
  await fresh
})

test('a risky call passes through untouched, whatever it does or however it ends', async ($: any, on: any) => {
  const pc = computer(on)
  const { call } = await bash($, pc, 'u1', 'rm -rf ./build')
  await until(() => pc.calls.length > 0)
  expect(pc.calls).toEqual([{ tool: 'Bash', command: 'rm -rf ./build', tool_use_id: 'u1' }]) // as made, not changed
  pc.settle('u1', { result: { stdout: '', stderr: '' }, context: ['kept'] })
  expect(await call).toEqual({ result: { stdout: '', stderr: '' }, context: ['kept'] })
})

// --- e4: the ghost -------------------------------------------------------------------------------------------------

const DELETING = ['rm ./one-file', 'git rm ./one-file', 'find ./fixture -name one-file -delete', 'unlink ./one-file',
                  'rm -f a b c d', 'rm ./a ./b ./c', 'find . -name "*.tmp" -exec rm {} \\;', 'git rm -r ./old',
                  'find . -name "*.log" -print0 | xargs -0 rm', 'cd x && rm ./y', 'command rm ./x',
                  'find . -newermt 2020-01-01 -delete', "find . -name '-x' -delete"]
const NOT_DELETING = ['ls ./fixture', 'find ./fixture -print', 'git status', 'git rm --dry-run ./one-file',
                      'git rm -n ./one-file', 'git rm --cached ./one-file', "printf '%s' 'rm ./one-file'",
                      'echo unlink ./one-file', 'ls # rm ./one-file', 'rmdir_notes', 'rmdir ./empty', 'rm', 'rm --help',
                      'git commit -m "rm ./one-file"',
                      // a value of find's that says -delete, and commands only looked up
                      "find . -name '-delete' -print", "find . -path '*/-delete/*' -print", 'find . -iname -delete',
                      "find . -regex '.*-delete' -print", "find . -printf '%p -delete\\n'",
                      "find . -fprintf out.txt '-delete' -print", 'command -v rm git', 'command -V rm',
                      'command -pv unlink', 'sudo command -v rm', 'type rm', 'type -a unlink', 'which rm', 'hash rm']

test('a command that deletes even one file says claude.deleted once it succeeded, a multi-file one once', async ($: any, on: any) => {
  const pc = computer(on)
  for (const [k, command] of DELETING.entries()) {
    const { call } = await bash($, pc, 'd' + k, command)
    await flush()
    expect([command, pc.moments().filter((m) => m === 'claude.deleted').length]).toEqual([command, k]) // not before it ran
    pc.settle('d' + k)
    await call
    await sent(pc, k + 1)
    expect([command, pc.moments().filter((m) => m === 'claude.deleted').length]).toEqual([command, k + 1])
  }
  expect(pc.moments().includes('claude.risky')).toBe(false) // none of these is risky
})

test('no ghost for what deletes nothing, nor for a deletion that failed or was refused', async ($: any, on: any) => {
  const pc = computer(on, { verdicts: { refused: { decision: 'deny', reason: 'a rule' } } })
  for (const [k, command] of NOT_DELETING.entries()) {
    const { call } = await bash($, pc, 'k' + k, command)
    await flush()
    pc.settle('k' + k)
    await call
  }
  const { call: failing } = await bash($, pc, 'f1', 'rm ./missing')
  await flush()
  pc.settle('f1', { isError: true, result: 'rm: cannot remove', text: 'rm: cannot remove' })
  await failing
  const { call: refused } = await bash($, pc, 'refused', 'rm ./kept')
  await flush()
  await $.tool.check({ tool: 'Bash', input: { command: 'rm ./kept' }, tool_use_id: 'refused' })
  pc.settle('refused', { deny: 'Permission to use Bash has been denied' })
  await refused
  await flush()
  expect(pc.moments().includes('claude.deleted')).toBe(false)
  const { call: fresh } = await bash($, pc, 'g1', 'rm ./gone') // a real deletion afterwards still says so
  await flush()
  pc.settle('g1')
  await fresh
  await flush()
  expect(pc.moments()).toContain('claude.deleted')
})

test('rm -rf is both: the courtroom as it starts, the ghost once it is done; drawings of it add nothing', async ($: any, on: any) => {
  const pc = computer(on)
  const { call } = await bash($, pc, 'b1', 'rm -rf ./build')
  await flush()
  expect(pc.moments()).toEqual(['claude.risky'])
  pc.settle('b1')
  await call
  for (let k = 0; k < 5; k++) {
    await $.ui.render({ surface: 'terminal', component: 'ToolGroup', requestId: 'g', props: { calls: [{ tool_use_id: 'b1',
      tool: 'Bash', input: { command: 'rm -rf ./build' }, isRunning: false, isErrored: false, isInterrupted: false,
      output: { stdout: '' } }] } })
  }
  await flush()
  expect(pc.moments()).toEqual(['claude.risky', 'claude.deleted'])
})

// --- e7: the back turned -------------------------------------------------------------------------------------------

test('capitals: at least eight letters, four in five of them capitals (digits and signs not counted)', async ($: any, on: any) => {
  const pc = computer(on)
  const cases: [string, string][] = [
    ['ABCDEFG', 'claude.calm'], ['ABCDEFGH', 'claude.rude'], ['ABCDEFGHij', 'claude.rude'], ['ABCDEFGhij', 'claude.calm'],
    ['please help', 'claude.calm'], ['1234567890 !!! ???', 'claude.calm'], ['ABCD-EFGH 12', 'claude.rude'],
    ['A B C D E F G H i j !!', 'claude.rude'], ['ABCDEFG 123456789', 'claude.calm'], ['FIX THIS NOW', 'claude.rude'],
    ['README 업데이트 해줘 API 문서도', 'claude.calm'], ['WHY IS THIS BROKEN?!', 'claude.rude'], ['', 'claude.calm'],
  ]
  for (const [text, name] of cases) {
    await typed($, text)
    await flush()
    expect([text, pc.moments().slice(-1)[0]]).toEqual([text, name])
  }
})

const SWEARS = ['fuck', 'Fuck this', 'fucks', 'fucked', 'FUCKING slow', 'fucker', 'motherfucker', 'shit', 'shitty code',
  'bullshit', 'damn', 'dammit', 'damnit', 'goddamn', 'wtf is this', 'stfu', 'bitch', 'asshole', 'bastard', 'oh, shit!',
  '씨발', '시발 왜 안돼', '씨팔', 'ㅅㅂ', 'ㅆㅂ', '개새끼', '병신같은 코드', '지랄하네', '존나 느려', '좆같네', 'fix it 씨발']
const BENIGN = ['class', 'passage', 'assess', 'shiitake', 'scrapbook', 'damnation', 'fucus', 'shitake', 'f*ck', 'sh!t',
  '시발점', '시발역에서', '병신년', '시바견', '존재', '지라프', '개새', 'bitchy?', 'ass', 'hell no', '미친 듯이 빠르다']

test('every swear on the lists turns the back, none of the near misses does', async ($: any, on: any) => {
  const pc = computer(on)
  for (const text of SWEARS) {
    await typed($, text)
    await flush()
    expect([text, pc.moments().slice(-1)[0]]).toEqual([text, 'claude.rude'])
  }
  for (const text of BENIGN) {
    await typed($, text)
    await flush()
    expect([text, pc.moments().slice(-1)[0]]).toEqual([text, 'claude.calm'])
  }
  await typed($, 'damn')
  await flush()
  expect(pc.moments().slice(-1)).toEqual(['claude.rude'])
})

test('only a prompt you typed counts: not a notification, another session, a plugin, nor words elsewhere', async ($: any, on: any) => {
  const pc = computer(on)
  for (const kind of ['task-notification', 'peer', 'peer-send-message', 'plugin', 'scheduled-trigger', 'channel', 'sdk',
                      'coordinator', 'unclassified']) {
    await typed($, 'WHAT THE FUCK IS THIS', kind)
  }
  const { call } = await bash($, pc, 'c1', 'echo "SHIT FUCK DAMN"')
  await flush()
  pc.settle('c1', { result: 'FUCK THIS OUTPUT' })
  await call
  await spinner($, 'Fuck')
  await flush()
  expect(pc.moments().filter((m) => m === 'claude.rude' || m === 'claude.calm')).toEqual([])
  await typed($, 'STOP IT RIGHT NOW', 'bridge') // your phone, through Remote Control: you
  await typed($, 'thanks, that is better')
  await flush()
  expect(pc.moments()).toEqual(['claude.rude', 'claude.calm'])
})

test('the prompt goes on untouched and nothing of it leaves', async ($: any, on: any) => {
  const pc = computer(on)
  expect(await typed($, 'CANARY-PROMPT-91 SHOUTING HERE')).toEqual({ text: 'CANARY-PROMPT-91 SHOUTING HERE' })
  expect(await typed($, 'a calm CANARY-PROMPT-92 one')).toEqual({ text: 'a calm CANARY-PROMPT-92 one' })
  await flush()
  expect(pc.moments()).toEqual(['claude.rude', 'claude.calm'])
  expect(JSON.stringify(pc.sent)).not.toContain('CANARY')
})

// --- x5: tool faces ------------------------------------------------------------------------------------------------

test('a tool that ran and failed makes Clawd dizzy, Bash or another, once', async ($: any, on: any) => {
  const pc = computer(on)
  const { call: one } = await bash($, pc, 'x1', 'npm test')
  await flush()
  pc.settle('x1', { isError: true, result: 'Exit code 1', text: 'Exit code 1' })
  await one
  const { call: two } = await started($, pc, { tool: 'Read', file_path: '/work/missing', tool_use_id: 'x2' })
  await flush()
  pc.settle('x2', { isError: true, result: 'File does not exist.', text: 'File does not exist.' })
  await two
  for (let k = 0; k < 4; k++) { // drawn again: nothing more
    await $.ui.render({ surface: 'terminal', component: 'ToolUse', requestId: 'x2', props: { tool_use_id: 'x2', tool: 'Read',
      input: {}, isRunning: false, isErrored: true, isInterrupted: false, output: 'File does not exist.' } })
  }
  await flush()
  expect(pc.moments()).toEqual(['claude.failed', 'claude.failed'])
})

test('no dizzy for a success that mentions errors, a call still running, one cut short or refused', async ($: any, on: any) => {
  const pc = computer(on, { verdicts: { asked: { decision: 'ask' }, denied: { decision: 'deny', reason: 'rule' } } })
  const { call: fine } = await bash($, pc, 'ok', 'grep -r error .')
  await flush()
  pc.settle('ok', { result: 'error: failed, failure, ERROR everywhere' })
  await fine
  const { call: long } = await bash($, pc, 'long', 'sleep 600')
  await flush()
  await $.ui.render({ surface: 'terminal', component: 'ToolUse', requestId: 'long', props: { tool_use_id: 'long', tool: 'Bash',
    input: {}, isRunning: true, isErrored: false, isInterrupted: false } })
  const { call: cut } = await bash($, pc, 'cut', 'sleep 5')
  await flush()
  await $.classic.PostToolUseFailure({ tool_name: 'Bash', tool_input: {}, tool_use_id: 'cut', error: 'Interrupted', is_interrupt: true })
  pc.settle('cut', { isError: true, result: 'Interrupted by user', text: 'Interrupted' })
  await cut
  const { call: drawnCut } = await bash($, pc, 'cut2', 'sleep 5')
  await flush()
  await $.ui.render({ surface: 'terminal', component: 'ToolUse', requestId: 'cut2', props: { tool_use_id: 'cut2', tool: 'Bash',
    input: {}, isRunning: false, isErrored: true, isInterrupted: true, output: 'Interrupted' } })
  pc.settle('cut2', { isError: true, result: 'Interrupted by user', text: 'Interrupted' })
  await drawnCut
  const { call: asked } = await bash($, pc, 'asked', 'npm publish') // you said no: drawn refused, never running
  await flush()
  await $.tool.check({ tool: 'Bash', input: { command: 'npm publish' }, tool_use_id: 'asked' })
  await $.ui.render({ surface: 'terminal', component: 'ToolUse', requestId: 'asked', props: { tool_use_id: 'asked', tool: 'Bash',
    input: {}, isRunning: false, isErrored: true, isInterrupted: false, output: 'The user refused this tool use' } })
  pc.settle('asked', { isError: true, result: 'The user does not want to proceed', text: 'refused' })
  await asked
  const { call: denied } = await bash($, pc, 'denied', 'curl example.com')
  await flush()
  await $.tool.check({ tool: 'Bash', input: { command: 'curl example.com' }, tool_use_id: 'denied' })
  pc.settle('denied', { isError: true, result: 'Permission denied by a rule', text: 'denied' })
  await denied
  const { call: classified } = await bash($, pc, 'auto', 'rm ./x')
  await flush()
  await $.classic.PermissionDenied({ tool_name: 'Bash', tool_input: {}, tool_use_id: 'auto', reason: 'auto mode' })
  pc.settle('auto', { isError: true, result: 'Denied by auto mode', text: 'denied' })
  await classified
  const { call: hook } = await bash($, pc, 'hook', 'make')
  await flush()
  pc.settle('hook', { deny: 'a hook said no' })
  await hook
  await flush()
  expect(pc.moments()).toEqual(['claude.ask', 'claude.answered']) // (the asked one's prompt), no dizzy at all
  pc.settle('long')
  await long
  await flush()
  expect(pc.moments()).toEqual(['claude.ask', 'claude.answered'])
})

test('asked, answered yes and then failed is a failure; a failure Claude Code reports after the run, too', async ($: any, on: any) => {
  const pc = computer(on, { verdicts: { y1: { decision: 'ask' }, y2: { decision: 'ask' } } })
  const { call: one } = await bash($, pc, 'y1', 'npm publish')
  await flush()
  await $.tool.check({ tool: 'Bash', input: { command: 'npm publish' }, tool_use_id: 'y1' })
  await $.ui.render({ surface: 'terminal', component: 'ToolUse', requestId: 'y1', props: { tool_use_id: 'y1', tool: 'Bash',
    input: {}, isRunning: true, isErrored: false, isInterrupted: false } }) // "Yes": drawn running
  pc.settle('y1', { isError: true, result: 'Exit code 1', text: 'Exit code 1' })
  await one
  const { call: two } = await bash($, pc, 'y2', 'npm publish') // quick: done before any drawing showed it running
  await flush()
  await $.tool.check({ tool: 'Bash', input: { command: 'npm publish' }, tool_use_id: 'y2' })
  await $.classic.PostToolUseFailure({ tool_name: 'Bash', tool_input: {}, tool_use_id: 'y2', error: 'Exit code 1', is_interrupt: false })
  pc.settle('y2', { isError: true, result: 'Exit code 1', text: 'Exit code 1' })
  await two
  await flush()
  expect(pc.moments().filter((m) => m === 'claude.failed').length).toBe(2)
})

test('a compaction of the conversation is one squeeze; one computed ahead, a subagent\'s or a skipped one is none',
  async ($: any, on: any) => {
    const pc = computer(on)
    const messages = [{ role: 'user', text: 'a', toolUses: [] }, { role: 'assistant', text: 'b', toolUses: [] }]
    const kept = await $.session.compact({ trigger: 'manual', messages })
    expect(kept).toEqual({ messages: [{ role: 'user', text: 'summary', toolUses: [] }] }) // passed on untouched
    await $.session.compact({ trigger: 'auto', messages })
    await $.session.compact({ trigger: 'precompute', messages })
    await $.session.compact({ trigger: 'auto', messages, agentId: 'agent-1' })
    await typed($, 'please compact the context, compaction now') // words alone
    const { call: tool } = await started($, pc, { tool: 'compact', tool_use_id: 'cmp' })
    await flush()
    pc.settle('cmp')
    await tool
    await flush()
    expect(pc.moments().filter((m) => m === 'claude.compact').length).toBe(2)
  })

test('a compaction vetoed sends nothing', async ($: any, on: any) => {
  const pc = computer(on, { skip: true })
  await $.session.compact({ trigger: 'manual', messages: [{ role: 'user', text: 'a', toolUses: [] }] })
  await flush()
  expect(pc.moments()).toEqual([])
})

test('a tool running is no snack: only /tokentv snack is', async ($: any, on: any) => {
  const pc = computer(on)
  const { call: long } = await bash($, pc, 'run', 'npm run build')
  await flush()
  for (let k = 0; k < 5; k++) {
    await spinner($, 'Building', { mode: 'tool-use' })
    await $.ui.render({ surface: 'terminal', component: 'ToolUse', requestId: 'run', props: { tool_use_id: 'run', tool: 'Bash',
      input: {}, isRunning: true, isErrored: false, isInterrupted: false } })
  }
  pc.settle('run')
  await long
  await flush()
  expect(pc.moments()).toEqual([])
  await $.command.run({ command: 'tokentv', args: 'snack' })
  await flush()
  expect(pc.moments()).toEqual(['claude.snack'])
})

// --- x6: the thinking word -----------------------------------------------------------------------------------------

test('the spinner\'s word while a turn runs: once, in capitals, and a new one when it changes', async ($: any, on: any) => {
  const pc = computer(on)
  await spinner($, 'Pondering') // no turn yet: nothing
  await $.turn.start({ text: 'go', turnId: 't1' })
  for (let k = 0; k < 6; k++) {
    expect(await spinner($, 'Pondering', { message: 'CANARY-MSG', suffix: 'CANARY-SUF' })).toEqual(DRAWN) // untouched
  }
  await spinner($, 'Accomplishing')
  await spinner($, 'Flibbertigibbeting') // 18 letters: not sent
  await flush()
  expect(pc.moments()).toEqual(['claude.word:PONDERING', 'claude.word:ACCOMPLISHING'])
  await $.turn.complete(turn('t1'))
  await spinner($, 'Pondering') // after the turn: nothing
  await flush()
  expect(pc.moments()).toEqual(['claude.word:PONDERING', 'claude.word:ACCOMPLISHING', 'claude.end'])
  expect(JSON.stringify(pc.sent)).not.toContain('CANARY')
})

test('only one word of letters, 1 to 14 of them, and nothing coerced', async ($: any, on: any) => {
  const pc = computer(on)
  await $.turn.start({ text: 'go', turnId: 't2' })
  const bad = ['', 'Fifteenletterss', 'two words', ' Pondering', 'Pondering ', 'Ponder1ng', 'Ponder_ing', 'Ponder-ing',
    'Pondering…', 'Pondering...', 'Pon\ndering', '\u001b[31mRed', '<b>Bold</b>', '$(rm -rf /)', '/private/path',
    'Pon\u200bdering', 'Sautéing', 'Créer', '생각중', '🤔', null, undefined, 42, ['Pondering'], { word: 'Pondering' }]
  for (const word of bad) await spinner($, word)
  await flush()
  expect(pc.moments()).toEqual([])
  for (const word of ['A', 'WWWWWWWWWWWWWW', 'Philosophising', 'pondering']) await spinner($, word)
  await flush()
  expect(pc.moments()).toEqual(['claude.word:A', 'claude.word:WWWWWWWWWWWWWW', 'claude.word:PHILOSOPHISING',
                                'claude.word:PONDERING'])
})

test('a word still on is said again every five minutes, so TokenTV knows the turn goes on', async ($: any, on: any) => {
  const clock = mock.clock(on, { now: 1_000_000 })
  const pc = computer(on)
  await $.turn.start({ text: 'go', turnId: 't3' })
  await spinner($, 'Brewing')
  await flush()
  await clock.advance(4 * 60 * 1000)
  await spinner($, 'Brewing', { mode: 'tool-use' })
  await flush()
  expect(pc.moments()).toEqual(['claude.word:BREWING'])
  await clock.advance(60 * 1000)
  await spinner($, 'Brewing', { mode: 'responding' })
  await flush()
  expect(pc.moments()).toEqual(['claude.word:BREWING', 'claude.word:BREWING'])
})

test('a turn cut short that showed a word says claude.stop, never a bow; one that showed none says nothing',
  async ($: any, on: any) => {
    const pc = computer(on)
    await $.turn.start({ text: 'go', turnId: 'a1' })
    await spinner($, 'Musing')
    await $.turn.complete(turn('a1', { isAborted: true, reason: 'aborted' }))
    await $.turn.complete(turn('a1', { isAborted: true, reason: 'aborted' })) // seen again: once
    await $.turn.start({ text: 'go', turnId: 'a2' })
    await $.turn.complete(turn('a2', { isAborted: true, reason: 'aborted' })) // no word shown: nothing to take away
    await $.turn.start({ text: 'go', turnId: 'a3' })
    await spinner($, 'Musing') // a new turn says its word again
    await $.turn.complete(turn('a3'))
    await flush()
    expect(pc.moments()).toEqual(['claude.word:MUSING', 'claude.stop', 'claude.word:MUSING', 'claude.end'])
  })

test('a subagent\'s turn neither ends the word nor bows; a session that ends mid-turn takes its word away',
  async ($: any, on: any) => {
    const pc = computer(on)
    await $.turn.start({ text: 'go', turnId: 'm1' })
    await spinner($, 'Herding')
    await $.turn.complete(turn('sub', { agentId: 'agent-1' }))
    await spinner($, 'Herding')
    await $.session.end({ reason: 'prompt_input_exit' })
    await flush()
    expect(pc.moments()).toEqual(['claude.word:HERDING', 'claude.stop'])
  })

// --- x9: sounds ----------------------------------------------------------------------------------------------------

async function waitAndEnd($: any, pc: any, id: string, turnId: string) {
  const { call } = await bash($, pc, id, 'npm publish')
  await flush()
  await $.tool.check({ tool: 'Bash', input: { command: 'npm publish' }, tool_use_id: id })
  for (let k = 0; k < 3; k++) {
    await $.ui.render({ surface: 'terminal', component: 'ToolUse', requestId: id, props: { tool_use_id: id, tool: 'Bash',
      input: {}, isRunning: false, isErrored: false, isInterrupted: false } }) // the dialog drawn again and again
  }
  await $.ui.render({ surface: 'terminal', component: 'ToolUse', requestId: id, props: { tool_use_id: id, tool: 'Bash',
    input: {}, isRunning: true, isErrored: false, isInterrupted: false } })
  pc.settle(id)
  await call
  await $.turn.complete(turn(turnId))
  await flush()
}

test('sounds are off unless you turn them on: the same moments go to TokenTV either way', async ($: any, on: any) => {
  const verdicts = { s1: { decision: 'ask' }, s2: { decision: 'ask' } }
  const pc = computer(on, { verdicts })
  await waitAndEnd($, pc, 's1', 'turn-1')
  expect(pc.plays).toEqual([])
  const before = pc.moments()
  expect(await $.command.run({ command: 'tokentv', args: 'sound on' })).toEqual({ text: 'Sounds on: a short sound on this ' +
    'computer when Claude Code waits for you and when a turn is done (Claude Code plays it on macOS; a Linux or Windows ' +
    'terminal stays silent).' })
  await flush()
  expect(pc.moments()).toEqual(before) // turning it on told TokenTV nothing
  expect(pc.writes).toEqual([['sound', true]])
  await waitAndEnd($, pc, 's2', 'turn-2')
  expect(pc.plays).toEqual([{ asset: 'sounds/wait.wav' }, { asset: 'sounds/done.wav' }]) // once each, however often drawn
  expect(pc.moments()).toEqual([...before, ...before]) // the same moments as with sounds off
})

test('sound off stops them at once; repeats are harmless; anything else changes nothing', async ($: any, on: any) => {
  const pc = computer(on, { verdicts: { o1: { decision: 'ask' }, o2: { decision: 'ask' } } })
  for (const args of ['sound on', 'sound on', 'SOUND  ON']) await $.command.run({ command: 'tokentv', args })
  for (const args of ['sound', 'sound maybe', 'sound on extra', 'sounds on', 'sound on CANARY-ARG', 'please sound on']) {
    expect(await $.command.run({ command: 'tokentv', args })).toEqual({ text: 'Try /tokentv pet, /tokentv snack, or /tokentv sound on|off.' })
  }
  expect(pc.store.sound).toBe(true)
  await waitAndEnd($, pc, 'o1', 'turn-o1')
  expect(pc.plays.length).toBe(2)
  expect(await $.command.run({ command: 'tokentv', args: 'sound off' })).toEqual({ text: 'Sounds off.' })
  await $.command.run({ command: 'tokentv', args: 'sound off' })
  await waitAndEnd($, pc, 'o2', 'turn-o2')
  expect(pc.plays.length).toBe(2)
  expect(pc.writes).toEqual([['sound', true], ['sound', true], ['sound', true], ['sound', false], ['sound', false]])
  expect(JSON.stringify([pc.sent, pc.writes, pc.plays])).not.toContain('CANARY')
})

test('no sound for a check nobody is asked, a second prompt of the same wait, a cut-short or a subagent\'s turn',
  async ($: any, on: any) => {
    const pc = computer(on, { store: { sound: true }, verdicts: { p1: { decision: 'ask' }, p2: { decision: 'ask' } } })
    const { call: allowed } = await bash($, pc, 'a1', 'ls')
    await flush()
    await $.tool.check({ tool: 'Bash', input: { command: 'ls' }, tool_use_id: 'a1' })
    pc.settle('a1')
    await allowed
    const { call: one } = await bash($, pc, 'p1', 'npm publish')
    const { call: two } = await bash($, pc, 'p2', 'npm publish')
    await flush()
    await $.tool.check({ tool: 'Bash', input: { command: 'npm publish' }, tool_use_id: 'p1' })
    await $.tool.check({ tool: 'Bash', input: { command: 'npm publish' }, tool_use_id: 'p2' }) // the same wait
    pc.settle('p1')
    pc.settle('p2')
    await one
    await two
    await $.turn.complete(turn('cut', { isAborted: true, reason: 'aborted' }))
    await $.turn.complete(turn('sub', { agentId: 'agent-2' }))
    await flush()
    expect(pc.plays).toEqual([{ asset: 'sounds/wait.wav' }])
    await $.turn.complete(turn('done-1'))
    await $.turn.complete(turn('done-2')) // two turns close together: two sounds (the bow's minute is the clock's)
    await flush()
    expect(pc.plays).toEqual([{ asset: 'sounds/wait.wav' }, { asset: 'sounds/done.wav' }, { asset: 'sounds/done.wav' }])
  })

test('sounds play with no TokenTV running, and on Windows, where nothing is sent', async ($: any, on: any) => {
  const pc = computer(on, { files: {}, sockets: [], store: { sound: true }, env: { USERPROFILE: 'C:/Users/u', OS: 'Windows_NT' },
                            verdicts: { w1: { decision: 'ask' } } })
  await $.turn.start({ text: 'go', turnId: 'w' })
  await spinner($, 'Pondering')
  await typed($, 'WHY WHY WHY WHY')
  const { call } = await bash($, pc, 'w1', 'rm -rf ./x')
  await flush()
  await $.tool.check({ tool: 'Bash', input: { command: 'rm -rf ./x' }, tool_use_id: 'w1' })
  pc.settle('w1', { isError: true, result: 'Exit code 1', text: 'Exit code 1' })
  await call
  await $.session.compact({ trigger: 'manual', messages: [{ role: 'user', text: 'a', toolUses: [] }] })
  await $.turn.complete(turn('w'))
  await flush()
  expect(pc.sent).toEqual([])
  expect(pc.plays).toEqual([{ asset: 'sounds/wait.wav' }, { asset: 'sounds/done.wav' }])
})

test('a player that fails or never ends holds nothing up, and a store that is not there leaves the session\'s setting',
  async ($: any, on: any) => {
    let hang = true
    const tried: any[] = []
    const pc = computer(on, { store: false, verdicts: { h1: { decision: 'ask' }, h2: { decision: 'ask' } }, audio: async ($: any, e: any) => {
      tried.push(e.clip)
      if (hang) await new Promise(() => {}) // never ends
      throw new Error('no audio device')
    } })
    await $.command.run({ command: 'tokentv', args: 'sound on' }) // no store: this session keeps it
    const started = Date.now()
    await waitAndEnd($, pc, 'h1', 'turn-h1')
    expect(Date.now() - started).toBeLessThan(1000)
    hang = false
    await waitAndEnd($, pc, 'h2', 'turn-h2')
    expect(tried.length).toBe(4)
    expect(pc.moments()).toEqual(['claude.ask', 'claude.answered', 'claude.end', 'claude.ask', 'claude.answered', 'claude.end'])
    expect(await $.command.run({ command: 'tokentv', args: 'sound off' })).toEqual({ text: 'Sounds off.' })
    await waitAndEnd($, pc, 'h3', 'turn-h3') // (h3 asks nobody: only its end) off: none
    expect(tried.length).toBe(4)
  })

// --- all of it ---------------------------------------------------------------------------------------------------

test('a prompt or a command of megabytes is read in its head only: the call goes on at once', async ($: any, on: any) => {
  const pc = computer(on)
  const prompt = 'a long paste, calm and quiet. '.repeat(70_000) // 2 MB
  let started = Date.now()
  expect(await typed($, prompt)).toEqual({ text: prompt })
  expect(Date.now() - started).toBeLessThan(500)
  const command = 'ls -la ./a "q u o t e d" $(pwd) | grep x; '.repeat(50_000) + 'rm -rf ./x' // 2 MB, risky at its end
  started = Date.now()
  const { call } = await bash($, pc, 'big', command)
  expect(Date.now() - started).toBeLessThan(500)
  pc.settle('big')
  await call
  await flush()
  expect(pc.moments()).toEqual(['claude.calm']) // (the risky end is past what is read)
  expect(pc.calls.map((c: any) => c.command)).toEqual([command]) // passed on whole
})

test('a command of many small parts is read in one pass: each reaches Claude Code within 100 ms',
  async ($: any, on: any) => {
    const pc = computer(on)
    const LONG: [string, string, string[]][] = [ // (what, the command, the names it brings)
      ['psql; x 25 000 (125 kB)', 'psql;'.repeat(25_000), []],
      ['psql -c DROP; x 4 000', 'psql -c "DROP TABLE t";'.repeat(4_000), ['claude.risky']],
      ['one find, 9 000 -exec', 'find .' + ' -exec true \\;'.repeat(9_000), []],
      ['one find, 8 000 values', 'find .' + " -name '-delete'".repeat(8_000) + ' -delete', ['claude.deleted']],
      ['$tag$ x 7 000 into psql', 'psql -c "' + 'SELECT $a$x$a$; '.repeat(7_000) + '"', []],
      ['quotes x 30 000 into psql', "psql -c \"" + "'x' ".repeat(30_000) + '"', []],
      ['comments x 9 000 into mysql', 'mysql -e "' + 'SELECT 1 # c\n'.repeat(9_000) + '"', []],
      ['command -v x 9 000', 'command -v rm;'.repeat(9_000), []],
      ['git push x 5 000', 'git push origin +a b c;'.repeat(5_000), ['claude.risky']],
    ]
    expect(LONG[0][1].length).toBe(125_000)
    for (const [k, [what, command, names]] of LONG.entries()) {
      const before = pc.sent.length
      const started = Date.now()
      const call = $.tool.call({ tool: 'Bash', command, tool_use_id: 'long' + k })
      call.catch(() => {})
      await until(() => pc.reached.length > k)
      expect([what, pc.reached[k] - started < 100]).toEqual([what, true])
      pc.settle('long' + k)
      await call
      await flush()
      expect([what, pc.moments().slice(before)]).toEqual([what, names])
    }
  })

test('only the names travel, each in the one envelope, and only to TokenTV\'s socket', async ($: any, on: any) => {
  const pc = computer(on)
  await $.turn.start({ text: 'CANARY-TURN-TEXT', turnId: 'CANARY-TURN-ID' })
  await spinner($, 'Pondering', { message: 'CANARY-SPIN' })
  await typed($, 'CANARY-PROMPT FUCK THIS')
  await typed($, 'calm CANARY-PROMPT-2')
  const { call } = await bash($, pc, 'CANARY-TOOL-ID', 'rm -rf /work/CANARY-PATH # CANARY-CMD')
  await flush()
  pc.settle('CANARY-TOOL-ID', { result: 'CANARY-OUTPUT' })
  await call
  const { call: failing } = await bash($, pc, 'CANARY-TOOL-2', 'cat /work/CANARY-PATH-2')
  await flush()
  pc.settle('CANARY-TOOL-2', { isError: true, result: 'CANARY-ERROR', text: 'CANARY-ERROR' })
  await failing
  await $.session.compact({ trigger: 'manual', instructions: 'CANARY-INSTRUCTIONS',
                            messages: [{ role: 'user', text: 'CANARY-MESSAGE', toolUses: [] }] })
  await $.turn.complete(turn('CANARY-TURN-ID', { answer: 'CANARY-ANSWER' }))
  await flush()
  expect(pc.moments()).toEqual(['claude.word:PONDERING', 'claude.rude', 'claude.calm', 'claude.risky', 'claude.deleted',
                                'claude.failed', 'claude.compact', 'claude.end'])
  expect(JSON.stringify(pc.sent)).not.toContain('CANARY')
  for (const one of pc.sent) {
    expect(one.url).toBe('http://127.0.0.1:8791/moment')
    expect(one.init).toEqual({ method: 'POST', headers: { 'content-type': 'application/json' },
                               body: JSON.stringify({ moment: named(one) }), socketPath: STATE + '/live.sock' })
  }
})
