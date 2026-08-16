import { existsSync, readdirSync } from 'node:fs'
import path from 'node:path'

import nextConfig from '../next.config'
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
} from '../src/services/api'

type Rewrite = {
  source: string
  destination: string
}

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message)
  }
}

async function getRewrites(): Promise<Rewrite[]> {
  const rewrites = nextConfig.rewrites
  assert(typeof rewrites === 'function', 'next.config.ts should define async rewrites()')

  const result = await rewrites()
  if (Array.isArray(result)) {
    return result as Rewrite[]
  }

  return [
    ...((result.beforeFiles ?? []) as Rewrite[]),
    ...((result.afterFiles ?? []) as Rewrite[]),
    ...((result.fallback ?? []) as Rewrite[]),
  ]
}

function requestUrl(input: Parameters<typeof fetch>[0]) {
  if (typeof input === 'string' || input instanceof URL) {
    return new URL(input, 'http://localhost:3000')
  }
  return new URL(input.url)
}

function getRequestBody(init: RequestInit | undefined) {
  assert(typeof init?.body === 'string', 'POST request should include a JSON string body')
  return JSON.parse(init.body) as Record<string, unknown>
}

async function verifyRewriteContract() {
  const mutableEnv = process.env as Record<string, string | undefined>
  const originalBackendUrl = process.env.AGENT_BACKEND_URL
  const originalLocalRuntime = process.env.VOICE_ACP_LOCAL_RUNTIME
  const originalNodeEnv = process.env.NODE_ENV
  mutableEnv.AGENT_BACKEND_URL = 'http://localhost:8000/'
  mutableEnv.VOICE_ACP_LOCAL_RUNTIME = ''
  mutableEnv.NODE_ENV = 'development'

  try {
    const stableRewrites = await getRewrites()
    assert(
      stableRewrites.some(
        (rewrite) => rewrite.source === '/api/get_config' && rewrite.destination === 'http://localhost:8000/get_config',
      ),
      'next.config.ts should rewrite /api/get_config to /get_config on the Python backend',
    )
    assert(
      stableRewrites.some(
        (rewrite) => rewrite.source === '/api/startAgent' && rewrite.destination === 'http://localhost:8000/startAgent',
      ),
      'next.config.ts should rewrite /api/startAgent to /startAgent on the Python backend',
    )
    assert(
      stableRewrites.some(
        (rewrite) => rewrite.source === '/api/stopAgent' && rewrite.destination === 'http://localhost:8000/stopAgent',
      ),
      'next.config.ts should rewrite /api/stopAgent to /stopAgent on the Python backend',
    )
    assert(
      !stableRewrites.some((rewrite) => rewrite.source.startsWith('/api/local/')),
      'normal web deployments must not publish local runtime rewrites',
    )

    mutableEnv.VOICE_ACP_LOCAL_RUNTIME = '1'
    const rewrites = await getRewrites()
    assert(
      rewrites.some(
        (rewrite) =>
          rewrite.source === '/api/local/workspace' && rewrite.destination === 'http://localhost:8000/local/workspace',
      ),
      'next.config.ts should rewrite /api/local/workspace to the loopback backend',
    )
    assert(
      rewrites.some(
        (rewrite) =>
          rewrite.source === '/api/local/workspace/browse' &&
          rewrite.destination === 'http://localhost:8000/local/workspace/browse',
      ),
      'next.config.ts should rewrite /api/local/workspace/browse to the loopback backend',
    )
    assert(
      rewrites.some(
        (rewrite) =>
          rewrite.source === '/api/local/workspace/browse/:operationId' &&
          rewrite.destination === 'http://localhost:8000/local/workspace/browse/:operationId',
      ),
      'next.config.ts should rewrite Project Folder picker polling to the loopback backend',
    )
    assert(
      rewrites.some(
        (rewrite) =>
          rewrite.source === '/api/local/runtime' && rewrite.destination === 'http://localhost:8000/local/runtime',
      ),
      'next.config.ts should rewrite /api/local/runtime to the loopback backend',
    )
  } finally {
    if (originalBackendUrl) {
      mutableEnv.AGENT_BACKEND_URL = originalBackendUrl
    } else {
      mutableEnv.AGENT_BACKEND_URL = ''
    }
    if (originalLocalRuntime) {
      mutableEnv.VOICE_ACP_LOCAL_RUNTIME = originalLocalRuntime
    } else {
      mutableEnv.VOICE_ACP_LOCAL_RUNTIME = ''
    }
    if (originalNodeEnv) {
      mutableEnv.NODE_ENV = originalNodeEnv
    } else {
      mutableEnv.NODE_ENV = ''
    }
  }
}

async function verifyRouteHandlersRemoved() {
  const apiDir = path.join(process.cwd(), 'app', 'api')
  if (!existsSync(apiDir)) {
    return
  }

  const pendingDirs = [apiDir]
  while (pendingDirs.length > 0) {
    const currentDir = pendingDirs.pop()
    assert(currentDir, 'Expected a directory to scan')

    for (const entry of readdirSync(currentDir, { withFileTypes: true })) {
      const entryPath = path.join(currentDir, entry.name)
      if (entry.isDirectory()) {
        pendingDirs.push(entryPath)
      }
      assert(!entryPath.endsWith(`${path.sep}route.ts`), `${entryPath} should not exist`)
    }
  }
}

async function verifyApiClientRequests() {
  const originalFetch = globalThis.fetch
  const seenPaths: string[] = []

  globalThis.fetch = (async (input, init) => {
    const url = requestUrl(input)
    seenPaths.push(url.pathname)

    if (url.pathname === '/api/get_config') {
      assert(init?.method === 'GET', 'GET /api/get_config should use GET')
      assert(url.searchParams.get('uid') === '1234', 'GET /api/get_config should pass the requested uid')
      assert(
        url.searchParams.get('channel') === 'test-channel',
        'GET /api/get_config should pass the requested channel',
      )

      return Response.json({
        code: 0,
        data: {
          app_id: 'stub-app-id',
          token: 'stub-token',
          uid: '1234',
          channel_name: 'test-channel',
          agent_uid: '9999',
        },
        msg: 'success',
      })
    }

    if (url.pathname === '/api/startAgent') {
      assert(init?.method === 'POST', 'POST /api/startAgent should use POST')
      const body = getRequestBody(init)
      assert(body.channelName === 'test-channel', 'POST /api/startAgent should include channelName')
      assert(body.rtcUid === 9999, 'POST /api/startAgent should include rtcUid')
      assert(body.userUid === 1234, 'POST /api/startAgent should include userUid')

      return Response.json({
        code: 0,
        data: {
          agent_id: 'mock-agent-id',
          channel_name: 'test-channel',
          status: 'started',
        },
        msg: 'success',
      })
    }

    if (url.pathname === '/api/stopAgent') {
      assert(init?.method === 'POST', 'POST /api/stopAgent should use POST')
      const body = getRequestBody(init)
      assert(body.agentId === 'mock-agent-id', 'POST /api/stopAgent should include agentId')
      return Response.json({ code: 0, msg: 'success' })
    }

    if (url.pathname === '/api/local/workspace') {
      const ready = {
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
      }
      if (init?.method === 'GET') {
        return Response.json({ code: 0, data: ready, msg: 'success' })
      }
      if (init?.method === 'DELETE') {
        return Response.json({
          code: 0,
          data: { ...ready, state: 'unconfigured', workspace: null },
          msg: 'success',
        })
      }
      assert(init?.method === 'PUT', 'Project Folder manual selection should use PUT')
      assert(getRequestBody(init).path === '/tmp/project', 'Project Folder PUT should include path')
      return Response.json({ code: 0, data: ready, msg: 'success' })
    }

    if (url.pathname === '/api/local/workspace/browse') {
      assert(init?.method === 'POST', 'Project Folder browse should use POST')
      return Response.json(
        {
          code: 0,
          data: { operation_id: 'browse-contract', state: 'picking' },
          msg: 'success',
        },
        { status: 202 },
      )
    }

    if (url.pathname === '/api/local/workspace/browse/browse-contract') {
      assert(init?.method === 'GET', 'Project Folder browse status should use GET')
      return Response.json({
        code: 0,
        data: {
          operation_id: 'browse-contract',
          state: 'ready',
          workspace: {
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
        },
        msg: 'success',
      })
    }

    if (url.pathname === '/api/local/runtime') {
      assert(
        init?.method === 'GET' || init?.method === 'POST',
        'local runtime readiness should use GET or explicit POST activation',
      )
      return Response.json({
        code: 0,
        data: {
          state: 'ready',
          workspace: {
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
          error: null,
        },
        msg: 'success',
      })
    }

    return Response.json({ detail: `Unexpected request path: ${url.pathname}` }, { status: 404 })
  }) as typeof fetch

  try {
    const config = await getConfig({ uid: 1234, channel: 'test-channel' })
    assert(config.token === 'stub-token', 'GET /api/get_config should return response data')

    const agentId = await startAgent('test-channel', 9999, 1234)
    assert(agentId === 'mock-agent-id', 'POST /api/startAgent should return the agent id')

    await stopAgent(agentId)

    const workspace = await getWorkspace()
    assert(workspace.state === 'ready', 'GET /api/local/workspace should return status')
    await browseWorkspace({ pollIntervalMs: 0 })
    await selectWorkspace('/tmp/project')
    const runtime = await getLocalRuntime()
    assert(runtime.state === 'ready', 'GET /api/local/runtime should return readiness')
    const startedRuntime = await startLocalRuntime()
    assert(startedRuntime.state === 'ready', 'POST /api/local/runtime should return readiness')
    const clearedWorkspace = await clearWorkspace()
    assert(clearedWorkspace.state === 'unconfigured', 'DELETE /api/local/workspace should clear the selection')

    assert(
      JSON.stringify(seenPaths) ===
        JSON.stringify([
          '/api/get_config',
          '/api/startAgent',
          '/api/stopAgent',
          '/api/local/workspace',
          '/api/local/workspace/browse',
          '/api/local/workspace/browse/browse-contract',
          '/api/local/workspace',
          '/api/local/runtime',
          '/api/local/runtime',
          '/api/local/workspace',
        ]),
      'API client should call the unversioned /api paths',
    )
  } finally {
    globalThis.fetch = originalFetch
  }
}

async function verifyLocalApiValidationErrors() {
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async (_input, init) => {
    if (init?.method === 'PUT') {
      return Response.json({ detail: 'Project Folder must be an absolute existing directory' }, { status: 400 })
    }
    return Response.json({ detail: 'Project Folder selection was cancelled' }, { status: 409 })
  }) as typeof fetch

  try {
    await selectWorkspace('relative').then(
      () => assert(false, 'invalid Project Folder selection should reject'),
      (error) =>
        assert(
          error instanceof Error && error.message === 'Project Folder must be an absolute existing directory',
          'Project Folder validation should preserve the bounded backend error',
        ),
    )
    await browseWorkspace().then(
      () => assert(false, 'cancelled Project Folder browse should reject'),
      (error) =>
        assert(
          error instanceof Error && error.message === 'Project Folder selection was cancelled',
          'picker cancellation should preserve the bounded backend error',
        ),
    )
  } finally {
    globalThis.fetch = originalFetch
  }
}

async function main() {
  await verifyRewriteContract()
  await verifyRouteHandlersRemoved()
  await verifyApiClientRequests()
  await verifyLocalApiValidationErrors()
  console.log('API contract checks passed')
}

await main()
