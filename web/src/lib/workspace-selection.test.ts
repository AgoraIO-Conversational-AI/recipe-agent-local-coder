import { expect, test } from 'bun:test'

import { getPreCallLocalAction } from './local-runtime'
import type { LocalRuntimeStatus, WorkspaceStatus } from './workspace'
import { applyBrowseOutcomeWithRuntimeRefresh, selectWorkspaceWithRuntimeRefresh } from './workspace-selection'

const workspace: WorkspaceStatus = {
  state: 'ready',
  profile: {
    id: 'codex',
    label: 'Codex',
    requires_primary_directory: true,
    supports_additional_directories: false,
  },
  workspace: { id: 'workspace-a', label: 'project', primary_directory: '/tmp/project' },
}

const failedRuntime: LocalRuntimeStatus = {
  state: 'failed',
  workspace,
  error: 'Could not start the local Codex runtime: missing executable',
}

test('failed replacement invalidates stale ready runtime before Start Conversation can reach Agora', async () => {
  const published: Array<LocalRuntimeStatus | null> = []
  let agoraCalls = 0

  await expect(
    selectWorkspaceWithRuntimeRefresh(
      async () => {
        throw new Error('Could not start the local Codex runtime: missing executable')
      },
      async () => failedRuntime,
      (runtime) => published.push(runtime),
    ),
  ).rejects.toThrow('missing executable')

  expect(published).toEqual([null, failedRuntime])
  const action = getPreCallLocalAction(true, workspace, published.at(-1) ?? null, false)
  if (action.kind === 'start') agoraCalls += 1
  expect(action.kind).toBe('configure')
  expect(agoraCalls).toBe(0)
})

test('cancelled browse is silent and does not refresh runtime', async () => {
  let runtimeCalls = 0
  const published: Array<LocalRuntimeStatus | null> = []

  const outcome = await applyBrowseOutcomeWithRuntimeRefresh(
    async () => ({ state: 'cancelled' }),
    async () => {
      runtimeCalls += 1
      throw new Error('must not run')
    },
    (runtime) => published.push(runtime),
  )

  expect(outcome).toEqual({ state: 'cancelled' })
  expect(runtimeCalls).toBe(0)
  expect(published).toEqual([])
})
