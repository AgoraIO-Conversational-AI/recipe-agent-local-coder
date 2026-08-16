import { afterEach, expect, test } from 'bun:test'

import {
  browseWorkspace,
  clearWorkspace,
  getConfig,
  getLocalRuntime,
  getWorkspace,
  selectWorkspace,
  startAgent,
  startLocalRuntime,
  stopAgent,
} from './api'

const originalFetch = globalThis.fetch
let lastCall: { url: string; init?: RequestInit }

afterEach(() => {
  globalThis.fetch = originalFetch
})

function mockFetch(status: number, body: unknown) {
  globalThis.fetch = (async (url: string | URL, init?: RequestInit) => {
    lastCall = { url: String(url), init }
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    })
  }) as typeof fetch
}

test('getConfig hits /api/get_config with query and returns data', async () => {
  mockFetch(200, {
    code: 0,
    msg: 'success',
    data: { app_id: 'a', token: 't', uid: '5', channel_name: 'c', agent_uid: '9' },
  })
  const data = await getConfig({ channel: 'c', uid: 5 })
  expect(data.token).toBe('t')
  expect(lastCall.url).toContain('/api/get_config')
  expect(lastCall.url).toContain('channel=c')
  expect(lastCall.url).toContain('uid=5')
})

test('startAgent posts the payload and returns agent_id', async () => {
  mockFetch(200, { code: 0, msg: 'success', data: { agent_id: 'agent-1' } })
  const id = await startAgent('ch', 111, 222)
  expect(id).toBe('agent-1')
  expect(lastCall.url).toContain('/api/startAgent')
  expect(lastCall.init?.method).toBe('POST')
  expect(JSON.parse(String(lastCall.init?.body))).toEqual({
    channelName: 'ch',
    rtcUid: 111,
    userUid: 222,
  })
})

test('stopAgent posts the agentId', async () => {
  mockFetch(200, {})
  await stopAgent('agent-1')
  expect(lastCall.url).toContain('/api/stopAgent')
  expect(JSON.parse(String(lastCall.init?.body))).toEqual({ agentId: 'agent-1' })
})

test('getConfig throws on an error response', async () => {
  mockFetch(500, { detail: 'boom' })
  await expect(getConfig()).rejects.toThrow('boom')
})

test('getWorkspace returns the local Workspace status', async () => {
  mockFetch(200, {
    code: 0,
    msg: 'success',
    data: {
      state: 'unconfigured',
      profile: {
        id: 'codex',
        label: 'Codex',
        requires_primary_directory: true,
        supports_additional_directories: false,
      },
      workspace: null,
    },
  })

  const status = await getWorkspace()

  expect(status.state).toBe('unconfigured')
  expect(lastCall.url).toContain('/api/local/workspace')
  expect(lastCall.init?.method).toBe('GET')
})

test('getLocalRuntime returns the local Codex readiness state', async () => {
  mockFetch(200, {
    code: 0,
    msg: 'success',
    data: {
      state: 'configuration_required',
      workspace: {
        state: 'unconfigured',
        profile: {
          id: 'codex',
          label: 'Codex',
          requires_primary_directory: true,
          supports_additional_directories: false,
        },
        workspace: null,
      },
      error: null,
    },
  })

  const status = await getLocalRuntime()

  expect(status.state).toBe('configuration_required')
  expect(lastCall.url).toContain('/api/local/runtime')
  expect(lastCall.init?.method).toBe('GET')
})

test('browseWorkspace posts only to the local browse route', async () => {
  mockFetch(200, {
    code: 0,
    msg: 'success',
    data: {
      state: 'ready',
      profile: {
        id: 'codex',
        label: 'Codex',
        requires_primary_directory: true,
        supports_additional_directories: false,
      },
      workspace: {
        id: 'workspace-a',
        label: 'project',
        primary_directory: '/tmp/project',
      },
    },
  })

  await browseWorkspace()

  expect(lastCall.url).toContain('/api/local/workspace/browse')
  expect(lastCall.init?.method).toBe('POST')
  expect(lastCall.init?.body).toBeUndefined()
})

test('selectWorkspace sends the advanced manual path', async () => {
  mockFetch(200, {
    code: 0,
    msg: 'success',
    data: {
      state: 'ready',
      profile: {
        id: 'codex',
        label: 'Codex',
        requires_primary_directory: true,
        supports_additional_directories: false,
      },
      workspace: {
        id: 'workspace-a',
        label: 'project',
        primary_directory: '/tmp/project',
      },
    },
  })

  await selectWorkspace('/tmp/project')

  expect(lastCall.init?.method).toBe('PUT')
  expect(JSON.parse(String(lastCall.init?.body))).toEqual({ path: '/tmp/project' })
})

test('clearWorkspace deletes only the saved local Workspace selection', async () => {
  mockFetch(200, {
    code: 0,
    msg: 'success',
    data: { state: 'unconfigured', profile: { id: 'codex' }, workspace: null },
  })

  await clearWorkspace()

  expect(lastCall.url).toContain('/api/local/workspace')
  expect(lastCall.init?.method).toBe('DELETE')
})

test('startLocalRuntime explicitly posts to the readiness route', async () => {
  mockFetch(200, {
    code: 0,
    msg: 'success',
    data: {
      state: 'ready',
      workspace: { state: 'ready', profile: { id: 'codex' }, workspace: { id: 'workspace-a' } },
      error: null,
    },
  })

  const status = await startLocalRuntime()

  expect(status.state).toBe('ready')
  expect(lastCall.url).toContain('/api/local/runtime')
  expect(lastCall.init?.method).toBe('POST')
})

test('local Workspace helpers preserve bounded backend validation errors', async () => {
  mockFetch(400, { detail: 'Project Folder must be an absolute existing directory' })

  await expect(selectWorkspace('relative')).rejects.toThrow('Project Folder must be an absolute existing directory')
})
