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

export type BrowseOperationState = 'picking' | 'ready' | 'cancelled' | 'failed'

export interface BrowseOperationStatus {
  operation_id: string
  state: BrowseOperationState
  workspace?: WorkspaceStatus | null
  error?: string | null
}

export type BrowseWorkspaceOutcome =
  | { state: 'ready'; workspace: WorkspaceStatus }
  | { state: 'cancelled' }

export type LocalRuntimeState = 'configuration_required' | 'starting' | 'authentication_required' | 'ready' | 'failed'

export interface LocalRuntimeStatus {
  state: LocalRuntimeState
  workspace: WorkspaceStatus
  error: string | null
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
