import type { LocalRuntimeStatus, WorkspaceStatus } from '@/lib/workspace'

const API_BASE_URL = '/api'

export interface GetConfigResponse {
  app_id: string
  token: string
  uid: string
  channel_name: string
  agent_uid: string
}

export async function getConfig(options?: { channel?: string; uid?: string | number }): Promise<GetConfigResponse> {
  const params = new URLSearchParams()
  if (options?.channel !== undefined && options.channel !== '') {
    params.set('channel', options.channel)
  }
  if (options?.uid !== undefined && options.uid !== '') {
    params.set('uid', String(options.uid))
  }

  const query = params.toString()
  const response = await fetch(`${API_BASE_URL}/get_config${query ? `?${query}` : ''}`, {
    method: 'GET',
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  const result = await response.json()
  if (result.code !== 0 || !result.data) {
    throw new Error(result.msg || 'Failed to get configuration')
  }
  return result.data
}

export async function startAgent(channelName: string, rtcUid: number, userUid: number): Promise<string> {
  const payload = { channelName, rtcUid, userUid }

  const response = await fetch(`${API_BASE_URL}/startAgent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  const result = await response.json()
  if (result.code !== 0 || !result.data?.agent_id) {
    throw new Error(result.msg || 'Failed to start agent')
  }
  return result.data.agent_id
}

export async function stopAgent(agentId: string): Promise<void> {
  if (!agentId) return

  const response = await fetch(`${API_BASE_URL}/stopAgent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agentId }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || `HTTP ${response.status}`)
  }
}

async function readWorkspaceResponse(response: Response): Promise<WorkspaceStatus> {
  return readLocalResponse<WorkspaceStatus>(response, 'Failed to get Project Folder configuration')
}

async function readLocalResponse<T>(response: Response, fallbackMessage: string): Promise<T> {
  const result = await response.json()
  if (!response.ok) {
    throw new Error(result.detail || `HTTP ${response.status}`)
  }
  if (result.code !== 0 || !result.data) {
    throw new Error(result.msg || fallbackMessage)
  }
  return result.data
}

export async function getWorkspace(): Promise<WorkspaceStatus> {
  return readWorkspaceResponse(await fetch(`${API_BASE_URL}/local/workspace`, { method: 'GET' }))
}

export async function getLocalRuntime(): Promise<LocalRuntimeStatus> {
  return readLocalResponse<LocalRuntimeStatus>(
    await fetch(`${API_BASE_URL}/local/runtime`, { method: 'GET' }),
    'Failed to get local Codex runtime readiness',
  )
}

export async function startLocalRuntime(): Promise<LocalRuntimeStatus> {
  return readLocalResponse<LocalRuntimeStatus>(
    await fetch(`${API_BASE_URL}/local/runtime`, { method: 'POST' }),
    'Failed to start the local Codex runtime',
  )
}

export async function browseWorkspace(): Promise<WorkspaceStatus> {
  return readWorkspaceResponse(await fetch(`${API_BASE_URL}/local/workspace/browse`, { method: 'POST' }))
}

export async function selectWorkspace(path: string): Promise<WorkspaceStatus> {
  return readWorkspaceResponse(
    await fetch(`${API_BASE_URL}/local/workspace`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),
  )
}

export async function clearWorkspace(): Promise<WorkspaceStatus> {
  return readWorkspaceResponse(await fetch(`${API_BASE_URL}/local/workspace`, { method: 'DELETE' }))
}
