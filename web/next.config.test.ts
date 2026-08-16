import { expect, test } from 'bun:test'

import { localRuntimeRewritesEnabled } from './next.config'

test('local rewrites require an explicit opt-in and loopback backend', () => {
  expect(localRuntimeRewritesEnabled(undefined, 'http://127.0.0.1:8000', 'development')).toBe(false)
  expect(localRuntimeRewritesEnabled('1', 'https://api.example.com', 'development')).toBe(false)
  expect(localRuntimeRewritesEnabled('1', 'http://127.0.0.1:8000', 'development')).toBe(true)
})

test('local rewrites stay unavailable in production deployments', () => {
  expect(localRuntimeRewritesEnabled('1', 'http://127.0.0.1:8000', 'production')).toBe(false)
})
