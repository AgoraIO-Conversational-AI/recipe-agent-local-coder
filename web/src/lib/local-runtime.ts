import type { LocalRuntimeStatus, WorkspaceStatus } from './workspace'

import { workspaceNeedsConfiguration } from './workspace'

export function getRuntimeStartBlock(
  workspace: WorkspaceStatus | null,
  runtime: LocalRuntimeStatus | null,
): string | null {
  if (!workspace || workspaceNeedsConfiguration(workspace)) {
    return 'Choose a valid Project Folder before starting a conversation.'
  }
  if (!runtime) {
    return 'Checking local Codex runtime readiness.'
  }
  if (runtime.state === 'ready') {
    return null
  }
  if (runtime.error) {
    return runtime.error
  }
  if (runtime.state === 'starting') {
    return 'Local Codex runtime is starting. Wait until it is ready before starting a conversation.'
  }
  if (runtime.state === 'authentication_required') {
    return 'Sign in to ChatGPT, then retry the local Codex runtime.'
  }
  if (runtime.state === 'failed') {
    return 'Could not start the local Codex runtime. Check the local error and retry.'
  }
  return 'Choose a valid Project Folder before starting a conversation.'
}
