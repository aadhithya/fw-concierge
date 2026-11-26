import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { HttpAgent } from '@ag-ui/client'
import { AssistantRuntimeProvider } from '@assistant-ui/react'
import { useAgUiRuntime } from '@assistant-ui/react-ag-ui'
import { Thread } from '@/components/assistant-ui/elements/thread.aui'
import { Badge } from '@/components/ui/badge'
import { TooltipProvider } from '@/components/ui/tooltip'
import { BookingPane } from './BookingPane'
import { ControlsPane, ControlsProvider, useControls } from './controls'
import { ResearchCard } from './ResearchCard'
import { SelectionProvider, useSelection } from './selection'

const STORE = 'concierge.researches' // the researches of this browser, so a refresh shows them again; their state is read from the API
const MAX = 8

const load = (): string[] => { try { return JSON.parse(localStorage.getItem(STORE) ?? '[]') } catch { return [] } }
const save = (ids: string[]) => { try { localStorage.setItem(STORE, JSON.stringify(ids)) } catch { /* private mode: fine */ } }

// The chat shows only words. Its tool calls (today's date, the agent's schema, starting the research) are not shown: the
// research card comes from featherweight's `background_started` event instead, which does not depend on a model streaming its
// tool calls. The thread folds tool calls into a collapsed "N tool calls" row by default, so both are replaced by nothing.
const NoToolCall = () => null
const NoToolGroup = ({ children }: { children?: ReactNode }) => <>{children}</>

export default function App() {
  return <ControlsProvider><SelectionProvider><Concierge /></SelectionProvider></ControlsProvider>
}

function Concierge() {
  const agent = useMemo(() => new HttpAgent({ url: '/api/agui' }), [])
  const runtime = useAgUiRuntime({ agent })
  const { controls } = useControls()
  const [jobs, setJobs] = useState<string[]>(load) // the researches, newest first (those of earlier visits are restored)
  const [live, setLive] = useState<Set<string>>(new Set()) // the ones started in this conversation: only they wake the chat

  useEffect(() => save(jobs), [jobs])

  // The delay of the mock provider service is a parameter of the chat request: the chat's model builds the research input, so the
  // server applies it when it submits the research (see ControlledJobClient in client.py).
  useEffect(() => { agent.headers = { ...agent.headers, 'x-provider-sleep': String(controls.sleepSeconds) } }, [agent, controls.sleepSeconds])

  const add = (jobId: string, isLive: boolean) => {
    setJobs((current) => [jobId, ...current.filter((id) => id !== jobId)].slice(0, MAX))
    if (isLive) setLive((current) => new Set(current).add(jobId))
  }

  // featherweight emits `background_started` (with the job id) on the chat stream when the chat starts a background job.
  useEffect(() => {
    const subscription = agent.subscribe({
      onCustomEvent: ({ event }) => {
        const jobId = event.name === 'background_started' ? event.value?.job_id : null
        if (jobId) add(jobId, true)
      },
    })
    return () => subscription.unsubscribe()
  }, [agent])

  return (
    <TooltipProvider>
      <AssistantRuntimeProvider runtime={runtime}>
        <div className="app-bg flex h-dvh flex-col text-foreground">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-2">
            <div className="flex items-center gap-2">
              <span className="font-semibold">fw-concierge</span>
              <Badge variant="outline">Simulated: fictional providers, no real bookings</Badge>
            </div>
          </header>
          <main className="grid min-h-0 flex-1 md:grid-cols-2">
            <section className="min-h-0 border-r">
              <Thread components={{ ToolFallback: NoToolCall, ToolGroup: NoToolGroup }} />
            </section>
            <RightPane jobs={jobs} live={live} onRetry={(id) => add(id, true)} />
          </main>
        </div>
      </AssistantRuntimeProvider>
    </TooltipProvider>
  )
}

/** The right-hand pane does not scroll itself. It has three parts: the research cards and the booking flow, each scrolling inside
 *  its own area, and the demo controls, anchored at the bottom. */
function RightPane({ jobs, live, onRetry }: { jobs: string[]; live: Set<string>; onRetry: (jobId: string) => void }) {
  const { selection } = useSelection()
  return (
    <aside className="flex min-h-0 flex-col overflow-hidden">
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2">
        {jobs.length === 0 && <div className="p-4 text-center text-sm text-muted-foreground">Describe what you need in the chat: the research appears here.</div>}
        {jobs.map((id, index) => <ResearchCard key={id} jobId={id} wake={live.has(id)} newest={index === 0} onRetry={onRetry} />)}
      </div>
      <div className={selection ? 'min-h-0 flex-1 overflow-y-auto border-t p-2' : 'shrink-0 border-t'}>
        <BookingPane />
      </div>
      <div className="shrink-0 border-t p-2"><ControlsPane /></div>
    </aside>
  )
}
