import { expect, test } from 'bun:test'

import { localRuntimeRewritesEnabled } from './next.config'

import nextConfig from './next.config'

function restoreEnvironment(name: string, value: string | undefined) {
  if (value === undefined) Reflect.deleteProperty(process.env, name)
  else process.env[name] = value
}

test('local rewrites require an explicit opt-in and loopback backend', () => {
  expect(localRuntimeRewritesEnabled(undefined, 'http://127.0.0.1:8000', 'development')).toBe(false)
  expect(localRuntimeRewritesEnabled('1', 'https://api.example.com', 'development')).toBe(false)
  expect(localRuntimeRewritesEnabled('1', 'http://127.0.0.1:8000', 'development')).toBe(true)
})

test('local rewrites stay unavailable in production deployments', () => {
  expect(localRuntimeRewritesEnabled('1', 'http://127.0.0.1:8000', 'production')).toBe(false)
})

test('local rewrites include picker operation polling when opted in', async () => {
  const previousBackend = process.env.AGENT_BACKEND_URL
  const previousOptIn = process.env.VOICE_ACP_LOCAL_RUNTIME
  const previousNodeEnv = process.env.NODE_ENV
  process.env.AGENT_BACKEND_URL = 'http://127.0.0.1:8000'
  process.env.VOICE_ACP_LOCAL_RUNTIME = '1'
  process.env.NODE_ENV = 'development'

  try {
    const rewrites = await nextConfig.rewrites!()
    expect(rewrites).toContainEqual({
      source: '/api/local/workspace/browse/:operationId',
      destination: 'http://127.0.0.1:8000/local/workspace/browse/:operationId',
    })
  } finally {
    restoreEnvironment('AGENT_BACKEND_URL', previousBackend)
    restoreEnvironment('VOICE_ACP_LOCAL_RUNTIME', previousOptIn)
    restoreEnvironment('NODE_ENV', previousNodeEnv)
  }
})
