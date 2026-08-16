export type WorkspaceState = 'unconfigured' | 'ready' | 'invalid'

export interface AgentProfile {
  id: string
  label: string
  requires_primary_directory: boolean
  supports_additional_directories: boolean
}

export interface WorkspaceScope {
  id: string
  label: string
  primary_directory: string
}

export interface WorkspaceStatus {
  state: WorkspaceState
  profile: AgentProfile
  workspace: WorkspaceScope | null
}

export const CODEX_PROFILE: AgentProfile = {
  id: 'codex',
  label: 'Codex',
  requires_primary_directory: true,
  supports_additional_directories: false,
}

export function workspaceNeedsConfiguration(status: WorkspaceStatus): boolean {
  return status.state !== 'ready' || status.workspace === null
}
