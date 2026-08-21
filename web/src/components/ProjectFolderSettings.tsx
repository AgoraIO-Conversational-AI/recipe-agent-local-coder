'use client'

import { FolderOpen, Loader2, Settings2, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import type { LocalRuntimeStatus, WorkspaceStatus } from '@/lib/workspace'
import { workspaceNeedsConfiguration } from '@/lib/workspace'
import { applyBrowseOutcomeWithRuntimeRefresh, selectWorkspaceWithRuntimeRefresh } from '@/lib/workspace-selection'
import { browseWorkspace, getLocalRuntime, selectWorkspace } from '@/services/api'

type SelectionOutcome =
  | { state: 'cancelled' }
  | { state: 'ready'; workspace: WorkspaceStatus; runtime: LocalRuntimeStatus }

type ProjectFolderSettingsProps = {
  open: boolean
  status: WorkspaceStatus | null
  runtimeStatus: LocalRuntimeStatus | null
  initialError: string | null
  onStatusChange: (status: WorkspaceStatus) => void
  onRuntimeStatusChange: (status: LocalRuntimeStatus | null) => void
  onClose: () => void
}

export function ProjectFolderSettings({
  open,
  status,
  runtimeStatus,
  initialError,
  onStatusChange,
  onRuntimeStatusChange,
  onClose,
}: ProjectFolderSettingsProps) {
  const [manualPath, setManualPath] = useState('')
  const [busyMode, setBusyMode] = useState<'browse' | 'manual' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const selectionInFlightRef = useRef(false)
  const mustConfigure = status ? workspaceNeedsConfiguration(status) : true
  const canClose = !mustConfigure && runtimeStatus?.state === 'ready'
  const visibleError = error ?? initialError
  const setupReady = status?.state === 'ready' && runtimeStatus?.state === 'ready'
  const isBusy = busyMode !== null

  useEffect(() => {
    if (!open) {
      setBusyMode(null)
      setError(null)
      setManualPath('')
      selectionInFlightRef.current = false
    }
  }, [open])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!open || !dialog) return
    const getFocusable = () =>
      Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), summary, a[href], [tabindex]:not([tabindex="-1"]):not([data-focus-guard])',
        ),
      ).filter((element) => element.getClientRects().length > 0 && !element.dataset.focusGuard)
    const retainKeyboardFocus = (event: FocusEvent) => {
      const target = event.target
      if (!(target instanceof HTMLElement)) return
      const focusable = getFocusable()
      if (!dialog.contains(target) || target.dataset.focusGuard === 'end') {
        focusable[0]?.focus()
      } else if (target.dataset.focusGuard === 'start') {
        focusable[focusable.length - 1]?.focus()
      }
    }
    document.addEventListener('focusin', retainKeyboardFocus, true)
    if (!dialog.open) dialog.showModal()
    const focusFrame = requestAnimationFrame(() => getFocusable()[0]?.focus())
    return () => {
      cancelAnimationFrame(focusFrame)
      document.removeEventListener('focusin', retainKeyboardFocus, true)
      if (dialog.open) dialog.close()
    }
  }, [open])

  if (!open) return null

  const runSelection = async (
    mode: 'browse' | 'manual',
    select: () => Promise<SelectionOutcome>,
    fallbackMessage: string,
  ) => {
    if (selectionInFlightRef.current) return
    selectionInFlightRef.current = true
    const previousError = error
    setBusyMode(mode)
    setError(null)
    try {
      const outcome = await select()
      if (outcome.state === 'cancelled') {
        setError(previousError)
        return
      }
      onStatusChange(outcome.workspace)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : fallbackMessage)
    } finally {
      selectionInFlightRef.current = false
      setBusyMode(null)
    }
  }

  const runBrowseSelection = () =>
    runSelection(
      'browse',
      () => applyBrowseOutcomeWithRuntimeRefresh(browseWorkspace, getLocalRuntime, onRuntimeStatusChange),
      'Could not finish local setup',
    )

  const runManualSelection = (path: string) =>
    runSelection(
      'manual',
      async () => ({
        state: 'ready',
        ...(await selectWorkspaceWithRuntimeRefresh(
          () => selectWorkspace(path),
          getLocalRuntime,
          onRuntimeStatusChange,
        )),
      }),
      'Could not select the Project Folder',
    )

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 px-4 py-8 backdrop-blur-sm">
      <dialog
        ref={dialogRef}
        aria-modal="true"
        aria-labelledby="project-folder-title"
        onCancel={(event) => {
          event.preventDefault()
          if (canClose) onClose()
        }}
        className="relative m-auto w-full max-w-[32rem] rounded-[24px] border-0 bg-card p-6 text-left text-foreground shadow-[0_24px_80px_rgba(0,0,0,0.48),0_1px_0_rgba(255,255,255,0.06)_inset] md:p-7"
      >
        <button
          type="button"
          data-focus-guard="start"
          aria-label="Return focus to the end of Project Folder settings"
          className="fixed h-px w-px opacity-0"
        />
        <header className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Settings2 className="h-5 w-5" aria-hidden="true" />
            </div>
            <div>
              <h2
                id="project-folder-title"
                className="text-xl font-semibold tracking-[-0.025em] text-foreground [text-wrap:balance]"
              >
                {mustConfigure ? 'Choose a Project Folder' : 'Project Folder'}
              </h2>
              <p className="mt-1 text-sm leading-6 text-muted-foreground [text-wrap:pretty]">
                {mustConfigure
                  ? 'Choose a folder once; setup finishes automatically.'
                  : 'Choose where Codex works. This sets ACP session context; it is not a filesystem sandbox.'}
              </p>
            </div>
          </div>
          {canClose ? (
            <button
              type="button"
              onClick={onClose}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-muted-foreground transition-[color,background-color,transform] duration-150 hover:bg-secondary hover:text-foreground active:scale-[0.96]"
              aria-label="Close Project Folder settings"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          ) : null}
        </header>

        {isBusy ? (
          <div
            className="mt-6 flex flex-col items-center rounded-2xl bg-secondary/70 px-5 py-8 text-center shadow-[0_1px_0_rgba(255,255,255,0.04)_inset]"
            aria-live="polite"
          >
            <Loader2 className="h-7 w-7 animate-spin text-primary" aria-hidden="true" />
            <p className="mt-4 text-sm font-semibold text-foreground">
              {busyMode === 'browse' ? 'Complete the folder selection' : 'Finishing local setup'}
            </p>
            <p className="mt-1.5 max-w-sm text-sm leading-6 text-muted-foreground">
              {busyMode === 'browse'
                ? 'Choose a folder in the macOS window. Setup will finish automatically.'
                : 'Starting the local coding agent for this Project Folder.'}
            </p>
          </div>
        ) : (
          <div className="mt-6 rounded-2xl bg-secondary/70 p-4 shadow-[0_1px_0_rgba(255,255,255,0.04)_inset]">
            <div className="flex items-center justify-between gap-4">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">Active Agent</p>
                <p className="mt-1 text-sm font-medium text-foreground">{status?.profile.label ?? 'Codex'}</p>
              </div>
              <span
                className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                  setupReady
                    ? 'bg-emerald-500/10 text-emerald-400'
                    : visibleError
                      ? 'bg-destructive/10 text-destructive'
                      : 'bg-amber-500/10 text-amber-300'
                }`}
              >
                {setupReady ? 'Configured' : visibleError ? 'Needs attention' : 'Required'}
              </span>
            </div>

            <div className="mt-4 min-w-0 rounded-xl bg-background/70 px-3.5 py-3">
              <p className="text-xs font-medium text-muted-foreground">Current folder</p>
              <p className="mt-1 truncate font-mono text-sm text-foreground">
                {status?.workspace?.primary_directory ?? 'No folder selected'}
              </p>
            </div>
          </div>
        )}

        {!isBusy && visibleError ? (
          <p className="mt-4 rounded-xl bg-destructive/10 px-3.5 py-3 text-sm text-destructive" aria-live="polite">
            {visibleError}
          </p>
        ) : null}

        <Button
          type="button"
          autoFocus
          onClick={() => void runBrowseSelection()}
          disabled={isBusy}
          className="mt-6 h-11 w-full rounded-xl bg-primary font-medium text-primary-foreground transition-transform duration-150 hover:bg-primary/90 active:scale-[0.96]"
        >
          {isBusy ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <FolderOpen className="h-4 w-4" aria-hidden="true" />
          )}
          {visibleError ? 'Try Again' : status?.state === 'ready' ? 'Choose Another Folder…' : 'Choose Project Folder…'}
        </Button>

        <details className="mt-4 rounded-xl bg-secondary/40 px-4 py-3 text-sm">
          <summary className="cursor-pointer select-none font-medium text-muted-foreground transition-colors hover:text-foreground">
            Advanced: enter a path
          </summary>
          <form
            className="mt-3 flex flex-col gap-2 sm:flex-row"
            onSubmit={(event) => {
              event.preventDefault()
              const path = manualPath.trim()
              if (path) void runManualSelection(path)
            }}
          >
            <label className="sr-only" htmlFor="manual-project-folder">
              Project Folder path
            </label>
            <input
              id="manual-project-folder"
              value={manualPath}
              onChange={(event) => setManualPath(event.target.value)}
              disabled={isBusy}
              placeholder="/Users/name/Projects/my-app"
              className="h-10 min-w-0 flex-1 rounded-lg bg-background px-3 font-mono text-sm text-foreground outline-none ring-1 ring-border transition-[box-shadow] focus:ring-2 focus:ring-primary"
            />
            <Button
              type="submit"
              variant="secondary"
              disabled={isBusy || manualPath.trim().length === 0}
              className="h-10 rounded-lg px-4 transition-transform duration-150 active:scale-[0.96]"
            >
              Use Path
            </Button>
          </form>
        </details>
        <button
          type="button"
          data-focus-guard="end"
          aria-label="Return focus to the start of Project Folder settings"
          className="fixed h-px w-px opacity-0"
        />
      </dialog>
    </div>
  )
}
