'use client'

import { Loader2, Settings2 } from 'lucide-react'

import { Button } from '@/components/ui/button'

type QuickstartPreCallCardProps = {
  isLoading: boolean
  error: string | null
  onStartConversation: () => void
  onOpenSettings?: () => void
}

export function QuickstartPreCallCard({
  isLoading,
  error,
  onStartConversation,
  onOpenSettings,
}: QuickstartPreCallCardProps) {
  return (
    <div
      className="mx-auto flex w-[min(92vw,26.25rem)] animate-fade-up flex-col items-center rounded-[20px] border border-[#2b2b2b] px-10 py-10 text-center shadow-[0_10px_24px_rgba(0,0,0,0.28)]"
      style={{
        backgroundImage:
          'linear-gradient(164.988deg, rgba(54,54,54,0.2) 1.0596%, rgba(0,0,0,0) 96.089%), linear-gradient(90deg, rgb(16,16,16) 0%, rgb(16,16,16) 100%)',
      }}
    >
      {onOpenSettings ? (
        <button
          type="button"
          onClick={onOpenSettings}
          className="self-end -mr-2 -mt-2 flex h-10 items-center gap-2 rounded-xl px-3 text-xs font-medium text-muted-foreground transition-[color,background-color,transform] duration-150 hover:bg-white/5 hover:text-foreground active:scale-[0.96]"
          aria-label="Open Project Folder settings"
        >
          <Settings2 className="h-4 w-4" aria-hidden="true" />
          Settings
        </button>
      ) : null}
      <h1 className="text-[28px] font-medium leading-[1.2] text-white">Try Agora&apos;s Voice Agent</h1>
      <p className="mt-[14px] text-sm font-medium leading-6 text-muted-foreground">
        Built on Agora&apos;s flagship Conversational AI engine, for effortless agentic conversations.
      </p>

      <Button
        onClick={onStartConversation}
        disabled={isLoading}
        className="mt-12 h-10 w-full rounded-lg border border-primary bg-primary text-sm font-medium text-black transition-transform duration-150 hover:border-white hover:bg-white hover:text-black active:scale-[0.96] disabled:hover:border-primary disabled:hover:bg-primary disabled:hover:text-black"
        aria-label={isLoading ? 'Starting conversation with AI agent' : 'Start conversation with AI agent'}
      >
        {isLoading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Starting...
          </>
        ) : (
          'Start Conversation'
        )}
      </Button>
      {error ? <p className="mt-3 text-xs text-destructive">{error}</p> : null}
    </div>
  )
}
