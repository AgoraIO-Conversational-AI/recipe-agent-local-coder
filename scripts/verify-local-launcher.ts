import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message)
}

const root = process.cwd()
const packageJson = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8')) as {
  scripts?: Record<string, string>
}
const launcher = path.join(root, 'scripts', 'run-local-codex.sh')

assert(
  packageJson.scripts?.['dev:codex'] === 'bun run dev:codex:check && bash scripts/run-local-codex.sh',
  'dev:codex should delegate sibling lifecycle cleanup to the local launcher',
)
assert(existsSync(launcher), 'local launcher script should exist')

const source = readFileSync(launcher, 'utf8')
assert(source.includes('trap cleanup EXIT INT TERM'), 'launcher should clean up on SIGINT and SIGTERM')
assert(source.includes('concurrently -k'), 'launcher should terminate the sibling when either child exits')

async function waitForPid(pathname: string): Promise<number> {
  const deadline = Date.now() + 5_000
  while (Date.now() < deadline) {
    if (existsSync(pathname)) return Number(readFileSync(pathname, 'utf8').trim())
    await Bun.sleep(25)
  }
  throw new Error(`Timed out waiting for child PID at ${pathname}`)
}

async function waitForExit(pid: number): Promise<void> {
  const deadline = Date.now() + 5_000
  while (Date.now() < deadline) {
    try {
      process.kill(pid, 0)
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ESRCH') return
      throw error
    }
    await Bun.sleep(25)
  }
  throw new Error(`Timed out waiting for child ${pid} to exit`)
}

function childCommand(pidPath: string, body: string): string {
  return `sh -c 'echo $$ > "${pidPath}"; ${body}'`
}

function startLauncher(backend: string, frontend: string, args: string[] = []) {
  return Bun.spawn({
    cmd: ['bash', 'scripts/run-local-codex.sh', ...args],
    cwd: process.cwd(),
    env: {
      ...process.env,
      LOCAL_BACKEND_COMMAND: backend,
      LOCAL_FRONTEND_COMMAND: frontend,
    },
    stdout: 'ignore',
    stderr: 'ignore',
  })
}

const overrideProcess = startLauncher(
  `sh -c 'test "$VOICE_ACP_WORKSPACE" = "/tmp/voice acp workspace" && test "$VOICE_ACP_COMMAND_JSON" = "[\\"custom-acp\\",\\"--stdio\\"]"'`,
  'sh -c \'trap "exit 0" INT TERM; while :; do sleep 1; done\'',
  ['--workspace', '/tmp/voice acp workspace', '--acp-command-json', '["custom-acp","--stdio"]'],
)
assert((await overrideProcess.exited) === 0, 'advanced launcher overrides should reach children as opaque env values')

const invalidArgumentProcess = startLauncher('exit 0', 'exit 0', ['--unknown-option'])
assert((await invalidArgumentProcess.exited) !== 0, 'unknown launcher arguments should fail closed')

const failedChildDirectory = mkdtempSync(path.join(tmpdir(), 'voice-acp-launcher-failure-'))
try {
  const backendPidPath = path.join(failedChildDirectory, 'backend.pid')
  const frontendPidPath = path.join(failedChildDirectory, 'frontend.pid')
  const launcherProcess = startLauncher(
    childCommand(backendPidPath, 'sleep 0.2; exit 23'),
    childCommand(frontendPidPath, 'trap "exit 0" INT TERM; while :; do sleep 1; done'),
  )
  const frontendPid = await waitForPid(frontendPidPath)
  const exitCode = await launcherProcess.exited

  assert(exitCode !== 0, 'a failing child should produce a failing launcher status')
  await waitForExit(frontendPid)
} finally {
  rmSync(failedChildDirectory, { recursive: true, force: true })
}

for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  const signalChildDirectory = mkdtempSync(path.join(tmpdir(), 'voice-acp-launcher-signal-'))
  try {
    const backendPidPath = path.join(signalChildDirectory, 'backend.pid')
    const frontendPidPath = path.join(signalChildDirectory, 'frontend.pid')
    const launcherProcess = startLauncher(
      childCommand(backendPidPath, 'trap "exit 0" INT TERM; while :; do sleep 1; done'),
      childCommand(frontendPidPath, 'trap "exit 0" INT TERM; while :; do sleep 1; done'),
    )
    const [backendPid, frontendPid] = await Promise.all([waitForPid(backendPidPath), waitForPid(frontendPidPath)])

    process.kill(launcherProcess.pid, signal)
    await launcherProcess.exited
    await Promise.all([waitForExit(backendPid), waitForExit(frontendPid)])
  } finally {
    rmSync(signalChildDirectory, { recursive: true, force: true })
  }
}

console.log('Local launcher cleanup integration checks passed')
