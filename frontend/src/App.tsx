import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { HttpAgent } from '@ag-ui/client'
import { AssistantRuntimeProvider, type ToolCallMessagePartProps } from '@assistant-ui/react'
import { useAgUiRuntime } from '@assistant-ui/react-ag-ui'
import { Thread } from '@/components/assistant-ui/elements/thread.aui'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { TooltipProvider } from '@/components/ui/tooltip'
import { getOutage, setOutage } from './api'
import { BookingPane } from './BookingPane'
import { ResearchCard } from './ResearchCard'
import { SelectionProvider } from './selection'

const LAST_JOB = 'concierge.lastJob' // so a refresh can show the research again; the state itself is read from the API

const remember = (id: string) => { try { localStorage.setItem(LAST_JOB, id) } catch { /* private mode: fine */ } }
const recall = () => { try { return localStorage.getItem(LAST_JOB) } catch { return null } }

/** How the chat renders a tool call. The framework's `start_background` call (the research job) becomes the research card;
 *  the chat agent's other tool calls (such as looking up today's date) are not shown. */
function ToolCall({ toolName, result }: ToolCallMessagePartProps) {
  if (toolName !== 'start_background') return null
  const started = typeof result === 'string' ? safeJson(result) : result
  if (!started?.job_id) return <div className="my-2 text-sm text-muted-foreground">Starting the research…</div>
  return <ResearchCard jobId={started.job_id} onJob={remember} wake />
}
// The thread folds tool calls into a collapsed "N tool calls" group by default. The research card must stay visible.
const PlainGroup = ({ children }: { children?: ReactNode }) => <>{children}</>
const safeJson = (text: string) => { try { return JSON.parse(text) } catch { return null } }

export default function App() {
  const agent = useMemo(() => new HttpAgent({ url: '/api/agui' }), [])
  const runtime = useAgUiRuntime({ agent })
  const [outage, setOutageState] = useState(false)
  const [last, setLast] = useState<string | null>(recall)
  const [showLast, setShowLast] = useState(false)

  useEffect(() => { getOutage().then((o) => setOutageState(o.enabled)).catch(() => {}) }, [])

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
            <div className="flex items-center gap-4 text-sm">
              {last && <Button size="sm" variant="ghost" onClick={() => setShowLast((v) => !v)}>Last research</Button>}
              <label className="flex items-center gap-2 text-muted-foreground">
                Simulate outage in booking preparation
                <Switch checked={outage} onCheckedChange={(on) => { setOutageState(on); setOutage(on) }} />
              </label>
            </div>
          </header>
          {showLast && last && (
            <div className="mx-auto w-full max-w-2xl px-4"><ResearchCard jobId={last} onJob={(id) => { remember(id); setLast(id) }} /></div>
          )}
          <main className="grid min-h-0 flex-1 md:grid-cols-2">
            <section className="min-h-0 border-r"><Thread components={{ ToolFallback: ToolCall, ToolGroup: PlainGroup }} /></section>
            <aside className="min-h-0 overflow-y-auto"><BookingPane /></aside>
          </main>
        </div>
      </AssistantRuntimeProvider>
      </SelectionProvider>
    </TooltipProvider>
  )
}
