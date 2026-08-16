import { expect, test } from 'bun:test'

import { CODEX_PROFILE, type WorkspaceStatus, workspaceNeedsConfiguration } from './workspace'

function status(state: WorkspaceStatus['state']): WorkspaceStatus {
  return {
    state,
    profile: CODEX_PROFILE,
    workspace:
      state === 'unconfigured'
        ? null
        : {
            id: 'workspace-a',
            label: 'project',
            primary_directory: '/tmp/project',
          },
  }
}

test('configuration gate blocks missing and invalid Workspace Scopes', () => {
  expect(workspaceNeedsConfiguration(status('unconfigured'))).toBe(true)
  expect(workspaceNeedsConfiguration(status('invalid'))).toBe(true)
})

test('configuration gate clears only for a ready Workspace Scope', () => {
  expect(workspaceNeedsConfiguration(status('ready'))).toBe(false)
})
