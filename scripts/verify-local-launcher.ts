import { existsSync, readFileSync } from 'node:fs'
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

console.log('Local launcher contract checks passed')
