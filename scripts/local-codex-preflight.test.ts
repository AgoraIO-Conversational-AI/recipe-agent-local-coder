import { expect, test } from 'bun:test'

import { validateLocalCodexPreflight } from './local-codex-preflight'

const validEnv = [
  'AGORA_APP_ID=0123456789abcdef0123456789abcdef',
  'AGORA_APP_CERTIFICATE=fedcba9876543210fedcba9876543210',
].join('\n')

const validRuntime = {
  platform: 'darwin',
  arch: 'arm64',
  availableCommands: new Set(['bun', 'node', 'python3']),
  envFileContents: validEnv,
}

test('preflight accepts the certified platform, runtimes, and usable Agora config', () => {
  expect(validateLocalCodexPreflight(validRuntime)).toEqual([
    'macOS Apple Silicon available',
    'bun, node, and python3 available',
    'Agora App ID and App Certificate configured',
  ])
})

test('preflight rejects non-certified platforms before local readiness', () => {
  expect(() => validateLocalCodexPreflight({ ...validRuntime, platform: 'linux' })).toThrow(
    'Local Codex runtime requires macOS',
  )
  expect(() => validateLocalCodexPreflight({ ...validRuntime, arch: 'x64' })).toThrow(
    'Local Codex runtime requires Apple Silicon',
  )
})

test('preflight reports missing runtimes without invoking them', () => {
  expect(() =>
    validateLocalCodexPreflight({
      ...validRuntime,
      availableCommands: new Set(['bun', 'python3']),
    }),
  ).toThrow('Missing required local runtime: node')
})

test('preflight rejects placeholders and never includes secret values', () => {
  const placeholder = ['AGORA_APP_ID=your_agora_app_id', 'AGORA_APP_CERTIFICATE=top-secret-certificate'].join('\n')

  try {
    validateLocalCodexPreflight({ ...validRuntime, envFileContents: placeholder })
    throw new Error('Expected invalid Agora configuration to fail')
  } catch (error) {
    expect(error).toBeInstanceOf(Error)
    expect((error as Error).message).toBe('Configure a usable AGORA_APP_ID in server/.env.local')
    expect((error as Error).message).not.toContain('top-secret-certificate')
  }
})
