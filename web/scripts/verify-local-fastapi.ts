import { existsSync } from 'node:fs'
import path from 'node:path'

import nextConfig from '../next.config'

type Rewrite = {
  source: string
  destination: string
}

type BunRuntime = typeof globalThis & {
  Bun: {
    sleep: (ms: number) => Promise<void>
    spawn: (options: {
      cmd: string[]
      cwd: string
      env: Record<string, string | undefined>
      stdout: 'ignore'
      stderr: 'pipe'
    }) => {
      kill: () => void
      exited: Promise<number>
      exitCode: number | null
      stderr: ReadableStream<Uint8Array> | null
    }
    spawnSync: (options: {
      cmd: string[]
      cwd: string
      stderr: 'pipe'
      stdout: 'ignore'
    }) => {
      exitCode: number
      stderr: { toString: () => string }
    }
  }
}

const bunRuntime = globalThis as BunRuntime

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message)
  }
}

function getJson(response: Response) {
  return response.json() as Promise<Record<string, unknown>>
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

async function requestViaRewrite(sourceUrl: string, init?: RequestInit) {
  const source = new URL(sourceUrl, 'http://localhost:3000')
  const rewrites = await getRewrites()
  const rewrite = rewrites.find((candidate) => candidate.source === source.pathname)
  assert(rewrite, `Missing rewrite for ${source.pathname}`)

  const target = new URL(rewrite.destination)
  target.search = source.search
  return fetch(target, init)
}

async function waitForHealthyBackend(baseUrl: string, timeoutMs: number) {
  const deadline = Date.now() + timeoutMs
  let lastError = 'backend did not start'

  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/get_config?uid=4321&channel=python-smoke`)
      if (response.ok) {
        return
      }
      lastError = `backend returned ${response.status}`
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error)
    }

    await bunRuntime.Bun.sleep(250)
  }

  throw new Error(`Timed out waiting for FastAPI backend: ${lastError}`)
}

async function main() {
  const mutableEnv = process.env as Record<string, string | undefined>
  const projectRoot = process.cwd()
  const serverRoot = path.resolve(projectRoot, '..', 'server')
  const venvPython = path.join(serverRoot, 'venv', 'bin', 'python')

  if (!existsSync(venvPython)) {
    throw new Error('Missing server/venv/bin/python. Run bun run setup:backend before verify:local.')
  }

  const dependencyCheck = bunRuntime.Bun.spawnSync({
    cmd: [venvPython, '-c', 'import dotenv, fastapi, uvicorn'],
    cwd: serverRoot,
    stderr: 'pipe',
    stdout: 'ignore',
  })
  if (dependencyCheck.exitCode !== 0) {
    const stderr = dependencyCheck.stderr.toString().trim()
    throw new Error(
      `The backend virtualenv is missing required packages. Run bun run setup:backend before verify:local.${stderr ? ` Python said: ${stderr}` : ''}`,
    )
  }

  const port = 43120 + Math.floor(Math.random() * 20)
  const backendUrl = `http://127.0.0.1:${port}`
  const originalBackendUrl = process.env.AGENT_BACKEND_URL
  const originalLocalRuntime = process.env.VOICE_ACP_LOCAL_RUNTIME
  const originalNodeEnv = process.env.NODE_ENV

  const serverProcess = bunRuntime.Bun.spawn({
    cmd: [venvPython, 'scripts/run_fake_server.py'],
    cwd: serverRoot,
    env: {
      ...process.env,
      AGORA_APP_ID: '0123456789abcdef0123456789abcdef',
      AGORA_APP_CERTIFICATE: 'fedcba9876543210fedcba9876543210',
      VOICE_ACP_LOCAL_RUNTIME: '1',
      PORT: String(port),
    },
    stdout: 'ignore',
    stderr: 'pipe',
  })

  try {
    await waitForHealthyBackend(backendUrl, 10_000)

    mutableEnv.AGENT_BACKEND_URL = backendUrl
    mutableEnv.VOICE_ACP_LOCAL_RUNTIME = '1'
    mutableEnv.NODE_ENV = 'development'

    const response = await requestViaRewrite('/api/get_config?uid=4321&channel=python-smoke')
    const body = await getJson(response)

    assert(response.status === 200, 'GET /api/get_config should proxy to the FastAPI app')
    assert(body.code === 0, 'GET /api/get_config should preserve the FastAPI success payload')

    const data = body.data as Record<string, unknown> | undefined
    assert(data?.uid === '4321', 'GET /api/get_config should preserve the requested uid through FastAPI')
    assert(
      data?.channel_name === 'python-smoke',
      'GET /api/get_config should preserve the requested channel through FastAPI',
    )
    assert(
      typeof data?.token === 'string' && data.token.length > 0,
      'GET /api/get_config should return a token from FastAPI',
    )
    assert(
      typeof data?.agent_uid === 'string' && data.agent_uid.length > 0,
      'GET /api/get_config should return an agent uid from FastAPI',
    )

    const zeroUidResponse = await requestViaRewrite('/api/get_config?uid=0&channel=python-smoke')
    const zeroUidBody = await getJson(zeroUidResponse)
    assert(zeroUidResponse.status === 200, 'GET /api/get_config?uid=0 should proxy to the FastAPI app')
    const zeroUidData = zeroUidBody.data as Record<string, unknown> | undefined
    assert(
      typeof zeroUidData?.uid === 'string' && zeroUidData.uid !== '0',
      'GET /api/get_config?uid=0 should generate an RTM-safe uid',
    )

    const runtimeResponse = await requestViaRewrite('/api/local/runtime')
    const runtimeBody = await getJson(runtimeResponse)
    assert(runtimeResponse.status === 200, 'GET /api/local/runtime should proxy to the FastAPI app')
    assert(runtimeBody.code === 0, 'GET /api/local/runtime should preserve the FastAPI success payload')
    assert(
      (runtimeBody.data as Record<string, unknown> | undefined)?.state === 'configuration_required',
      'GET /api/local/runtime should not start ACP without a Project Folder',
    )

    const startRuntimeResponse = await requestViaRewrite('/api/local/runtime', { method: 'POST' })
    const startRuntimeBody = await getJson(startRuntimeResponse)
    assert(startRuntimeResponse.status === 200, 'POST /api/local/runtime should be available only in local mode')
    assert(
      (startRuntimeBody.data as Record<string, unknown> | undefined)?.state === 'configuration_required',
      'POST /api/local/runtime should not start ACP without a Project Folder',
    )

    const invalidWorkspaceResponse = await requestViaRewrite('/api/local/workspace', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: 'relative-project' }),
    })
    const invalidWorkspaceBody = await getJson(invalidWorkspaceResponse)
    assert(invalidWorkspaceResponse.status === 400, 'invalid Project Folder selection should return 400')
    assert(
      invalidWorkspaceBody.detail === 'Project Folder must be an absolute existing directory',
      'Project Folder validation should return a bounded error',
    )

    const invalidShapeResponse = await requestViaRewrite('/api/local/workspace', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
    assert(invalidShapeResponse.status === 422, 'missing Project Folder path should return FastAPI validation error')

    const clearWorkspaceResponse = await requestViaRewrite('/api/local/workspace', { method: 'DELETE' })
    const clearWorkspaceBody = await getJson(clearWorkspaceResponse)
    assert(clearWorkspaceResponse.status === 200, 'DELETE /api/local/workspace should proxy successfully')
    assert(
      (clearWorkspaceBody.data as Record<string, unknown> | undefined)?.state === 'unconfigured',
      'DELETE /api/local/workspace should return the cleared status',
    )

    const startResponse = await requestViaRewrite('/api/startAgent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        channelName: 'python-smoke',
        rtcUid: 9999,
        userUid: 4321,
      }),
    })
    const startBody = await getJson(startResponse)
    assert(startResponse.status === 200, 'POST /api/startAgent should proxy to the FastAPI app')
    assert(startBody.code === 0, 'POST /api/startAgent should preserve the FastAPI success payload')
    assert(
      (startBody.data as Record<string, unknown> | undefined)?.agent_id === 'fake-agent-9999',
      'POST /api/startAgent should return the agent id from FastAPI',
    )

    const stopResponse = await requestViaRewrite('/api/stopAgent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agentId: 'fake-agent-9999' }),
    })
    const stopBody = await getJson(stopResponse)
    assert(stopResponse.status === 200, 'POST /api/stopAgent should proxy to the FastAPI app')
    assert(stopBody.code === 0, 'POST /api/stopAgent should preserve the FastAPI success payload')

    console.log('Local FastAPI app proxy smoke check passed')
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

    serverProcess.kill()
    await serverProcess.exited

    if (serverProcess.exitCode && serverProcess.exitCode !== 0) {
      const stderr = await new Response(serverProcess.stderr).text()
      if (stderr.trim()) {
        console.error(stderr.trim())
      }
    }
  }
}

await main()
