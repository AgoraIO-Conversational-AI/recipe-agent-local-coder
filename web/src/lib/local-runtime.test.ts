import { expect, test } from 'bun:test'

import { getPreCallLocalAction } from './local-runtime'
import type { LocalRuntimeStatus, WorkspaceStatus } from './workspace'

const savedWorkspace: WorkspaceStatus = {
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

function runtime(state: LocalRuntimeStatus['state'], error: string | null = null): LocalRuntimeStatus {
  return { state, workspace: savedWorkspace, error }
}

test('unknown local setup is checking rather than an error', () => {
  expect(getPreCallLocalAction(true, null, null, true)).toEqual({
    kind: 'checking',
    label: 'Checking local setup…',
    disabled: true,
    ready: false,
  })
})

test('missing Workspace routes the primary action to configuration', () => {
  expect(getPreCallLocalAction(true, null, null, false)).toEqual({
    kind: 'configure',
    label: 'Choose Project Folder',
    disabled: false,
    ready: false,
  })
})

test('ready Workspace and runtime enable conversation start', () => {
  expect(getPreCallLocalAction(true, savedWorkspace, runtime('ready'), false)).toEqual({
    kind: 'start',
    label: 'Start Conversation',
    disabled: false,
    ready: true,
  })
})

test('every non-ready runtime routes the primary action to Settings', () => {
  for (const state of ['configuration_required', 'starting', 'authentication_required', 'failed'] as const) {
    expect(getPreCallLocalAction(true, savedWorkspace, runtime(state, 'Bounded setup failure'), false)).toEqual({
      kind: 'configure',
      label: 'Choose Project Folder',
      disabled: false,
      ready: false,
    })
  }
})
