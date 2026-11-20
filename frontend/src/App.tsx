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
import { SelectionProvider } from './selection'

const LAST_JOB = 'concierge.lastJob' // so a refresh can show the research again; the state itself is read from the API

const remember = (id: string) => { try { localStorage.setItem(LAST_JOB, id) } catch { /* private mode: fine */ } }
const recall = () => { try { return localStorage.getItem(LAST_JOB) } catch { return null } }

// The chat shows only words. Its tool calls (today's date, the job's schema, starting the research) are not shown: the
// research card comes from featherweight's `background_started` event instead, which does not depend on a model streaming its
// tool calls. The thread folds tool calls into a collapsed "N tool calls" row by default, so both are replaced by nothing.
const NoToolCall = () => null
const NoToolGroup = ({ children }: { children?: ReactNode }) => <>{children}</>

export default function App() {
  return <ControlsProvider><Concierge /></ControlsProvider>
}

function Concierge() {
  const agent = useMemo(() => new HttpAgent({ url: '/api/agui' }), [])
  const runtime = useAgUiRuntime({ agent })
  const { controls } = useControls()
  const [jobs, setJobs] = useState<string[]>([]) // researches started in this conversation, newest first
  const [restored] = useState<string | null>(recall) // the last research of an earlier visit (shown after a refresh)

  // The delay of the mock provider service is a parameter of the chat request: the chat's model builds the job input, so the
  // server applies it when it submits the research (see ControlledJobClient in api.py).
  useEffect(() => { agent.headers = { ...agent.headers, 'x-provider-sleep': String(controls.sleepSeconds) } }, [agent, controls.sleepSeconds])

  // featherweight emits `background_started` (with the job id) on the chat stream when the chat starts a background agent.
  useEffect(() => {
    const subscription = agent.subscribe({
      onCustomEvent: ({ event }) => {
        const jobId = event.name === 'background_started' ? event.value?.job_id : null
        if (jobId) setJobs((current) => (current.includes(jobId) ? current : [jobId, ...current]))
      },
    })
    return () => subscription.unsubscribe()
  }, [agent])

  return (
    <TooltipProvider>
      <SelectionProvider>
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
            <aside className="min-h-0 space-y-2 overflow-y-auto p-2">
              {/* Live researches wake the chat when they end. A restored one (after a refresh) never does: the chat has no memory of it. */}
              {jobs.map((id) => <ResearchCard key={id} jobId={id} onJob={remember} wake />)}
              {jobs.length === 0 && restored && <ResearchCard jobId={restored} />}
              <BookingPane />
              <ControlsPane />
            </aside>
          </main>
        </div>
      </AssistantRuntimeProvider>
      </SelectionProvider>
    </TooltipProvider>
  )
}
