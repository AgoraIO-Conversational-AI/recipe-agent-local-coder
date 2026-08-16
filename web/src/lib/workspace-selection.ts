import type { LocalRuntimeStatus, WorkspaceStatus } from './workspace'

export async function selectWorkspaceWithRuntimeRefresh(
  select: () => Promise<WorkspaceStatus>,
  getRuntime: () => Promise<LocalRuntimeStatus>,
  publishRuntime: (runtime: LocalRuntimeStatus | null) => void,
): Promise<{ workspace: WorkspaceStatus; runtime: LocalRuntimeStatus }> {
  publishRuntime(null)
  try {
    const workspace = await select()
    const runtime = await getRuntime()
    if (runtime.state !== 'ready') {
      throw new Error(runtime.error ?? 'The local Codex runtime is not ready')
    }
    publishRuntime(runtime)
    return { workspace, runtime }
  } catch (error) {
    try {
      publishRuntime(await getRuntime())
    } catch {
      publishRuntime(null)
    }
    throw error
  }
}
