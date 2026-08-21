import { expect, test } from 'bun:test'

import { getPreCallLocalAction, getRuntimeStartBlock } from './local-runtime'
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

test('initial saved workspace blocks conversation when local authentication is required', () => {
  expect(getRuntimeStartBlock(savedWorkspace, runtime('authentication_required', 'Sign in to ChatGPT.'))).toBe(
    'Sign in to ChatGPT.',
  )
})

test('runtime readiness blocks every non-ready state with useful guidance', () => {
  expect(getRuntimeStartBlock(savedWorkspace, runtime('starting'))).toBe(
    'Local Codex runtime is starting. Wait until it is ready before starting a conversation.',
  )
  expect(getRuntimeStartBlock(savedWorkspace, runtime('authentication_required'))).toBe(
    'Sign in to ChatGPT, then retry the local Codex runtime.',
  )
  expect(getRuntimeStartBlock(savedWorkspace, runtime('failed', 'Local Codex failed to start.'))).toBe(
    'Local Codex failed to start.',
  )
  expect(getRuntimeStartBlock(savedWorkspace, runtime('configuration_required'))).toBe(
    'Choose a valid Project Folder before starting a conversation.',
  )
  expect(getRuntimeStartBlock(savedWorkspace, null)).toBe('Checking local Codex runtime readiness.')
  expect(getRuntimeStartBlock(savedWorkspace, runtime('ready'))).toBeNull()
})

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
