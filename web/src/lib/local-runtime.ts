import type { LocalRuntimeStatus, WorkspaceStatus } from './workspace'

import { workspaceNeedsConfiguration } from './workspace'

export type PreCallLocalAction = {
  kind: 'checking' | 'configure' | 'start'
  label: string
  disabled: boolean
  ready: boolean
}

export function getPreCallLocalAction(
  enabled: boolean,
  workspace: WorkspaceStatus | null,
  runtime: LocalRuntimeStatus | null,
  checking: boolean,
): PreCallLocalAction {
  if (!enabled) {
    return { kind: 'start', label: 'Start Conversation', disabled: false, ready: false }
  }
  if (checking) {
    return { kind: 'checking', label: 'Checking local setup…', disabled: true, ready: false }
  }
  if (!workspace || workspaceNeedsConfiguration(workspace) || runtime?.state !== 'ready') {
    return { kind: 'configure', label: 'Choose Project Folder', disabled: false, ready: false }
  }
  return { kind: 'start', label: 'Start Conversation', disabled: false, ready: true }
}
