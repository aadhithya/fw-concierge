import { useCallback, useEffect, useState } from 'react'
import { ChevronDownIcon, ChevronRightIcon } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { getJob, retryJob, when, type Booking, type Job } from './api'
import { useControls } from './controls'
import { useSelection } from './selection'
import { useWake } from './wake'

const STATE_STYLE: Record<Job['state'], string> = {
  queued: 'bg-zinc-700 text-zinc-100', running: 'bg-blue-600/80 text-white', completed: 'bg-emerald-600/80 text-white',
  failed: 'bg-red-600/80 text-white', cancelled: 'bg-zinc-700 text-zinc-100',
}

/** One research job: its interpreted criteria, live progress and the shortlist. The card collapses to one line; the newest one is
 *  open, and when a newer research arrives the older cards collapse. Retry starts a new research, which gets a card of its own. */
export function ResearchCard({ jobId, wake = false, newest = false, onRetry }: { jobId: string; wake?: boolean; newest?: boolean; onRetry?: (newJobId: string) => void }) {
  const [open, setOpen] = useState(newest)
  useEffect(() => { if (!newest) setOpen(false) }, [newest])
  const [job, setJob] = useState<Job | null>(null)
  const { selection, select } = useSelection()
  const { controls } = useControls()
  const [error, setError] = useState<string | null>(null)

  useWake(jobId, job?.wake ?? null, wake) // tells the chat how this research ended (live conversation only)

  const refresh = useCallback(() => getJob(jobId).then(setJob).catch((e) => setError(String(e.message))), [jobId])

  // The job state comes from the API, so a refresh (or a new browser) shows the same thing. The SSE stream only says "something changed".
  useEffect(() => {
    refresh()
    const events = new EventSource(`/api/jobs/${jobId}/stream`)
    events.addEventListener('progress', refresh)
    events.addEventListener('state', refresh)
    events.onerror = () => events.close() // the stream ends when the job is final
    return () => events.close()
  }, [jobId, refresh])

  if (error) return <Card className="my-3"><CardContent className="pt-4 text-red-400">{error}</CardContent></Card>
  if (!job) return <Card className="my-3"><CardContent className="pt-4 text-muted-foreground">Loading research…</CardContent></Card>

  const confirmed = job.booking // a booking made earlier (this also restores it after a refresh)
  const retry = async () => onRetry?.((await retryJob(jobId, controls.sleepSeconds)).job_id)
  return (
    <Card className="my-3 w-full">
      <CardHeader className="gap-1">
        <button type="button" className="flex w-full items-center justify-between gap-2 text-left" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          <CardTitle className="flex items-center gap-1 text-base">
            {open ? <ChevronDownIcon className="size-4" /> : <ChevronRightIcon className="size-4" />}
            Research <span className="font-mono text-xs text-muted-foreground">{job.job_id.slice(0, 8)}</span>
          </CardTitle>
          <Badge className={STATE_STYLE[job.state]}>{job.state}</Badge>
        </button>
        {!open && job.criteria && (
          <div className="truncate pl-5 text-xs text-muted-foreground">
            {job.criteria.location} · {job.criteria.date_from}{job.criteria.preferences.length > 0 && ` · ${job.criteria.preferences.join(', ')}`}
            {job.result && ` · ${job.result.shortlist.length} found`}
          </div>
        )}
      </CardHeader>
      {open && <CardContent className="space-y-4 text-sm">
        {job.criteria && (
          <div>
            <div className="mb-1 font-medium">How I read your request</div>
            <div className="text-muted-foreground">
              Physiotherapy · {job.criteria.location} · {job.criteria.date_from}
              {job.criteria.date_to !== job.criteria.date_from && ` to ${job.criteria.date_to}`}
              {job.criteria.preferences.length > 0 && ` · ${job.criteria.preferences.join(', ')}`}
            </div>
          </div>
        )}

        <ul className="space-y-0.5 text-xs text-muted-foreground">
          {job.progress.map((p) => <li key={p.seq}>· {p.message}</li>)}
        </ul>

        {(job.state === 'queued' || job.state === 'running') && <div className="text-xs text-muted-foreground">The research agent is waiting for the provider service…</div>}

        {job.state === 'failed' && (
          <div className="space-y-2 rounded-md border border-red-500/40 p-3">
            <div className="text-red-400">The research failed ({job.error}). See the progress lines above.</div>
            <Button size="sm" onClick={retry}>Retry research</Button>
          </div>
        )}

        {confirmed && <BookingView booking={confirmed} />}

        {job.state === 'completed' && job.result && !confirmed && (
          <div className="space-y-3">
            <div className="text-muted-foreground">{job.result.summary}</div>
            {job.result.shortlist.map((item) => (
              <div key={item.provider.id} className="space-y-2 rounded-md border p-3">
                <div className="flex items-center justify-between">
                  <div className="font-medium">{item.rank}. {item.provider.name}</div>
                  <div className="text-xs text-muted-foreground">{item.provider.neighbourhood} · {'€'.repeat(item.provider.price_band)}</div>
                </div>
                <div className="text-xs text-muted-foreground">{item.provider.description}</div>
                <div className="text-xs"><span className="text-muted-foreground">Why: </span>{item.reasons.join(' ')}</div>
                <div className="flex flex-wrap gap-2">
                  {item.slots.map((slot) => (
                    <Button key={slot.id} size="sm" variant={selection?.slot.id === slot.id ? 'default' : 'outline'}
                      onClick={() => select({ researchJobId: jobId, item, slot })}>
                      {when(slot.starts_at)}
                    </Button>
                  ))}
                </div>
              </div>
            ))}
            {job.result.shortlist.length === 0 && <div>No suitable provider was found. Try a wider area or different dates.</div>}
          </div>
        )}

      </CardContent>}
    </Card>
  )
}

function BookingView({ booking }: { booking: Booking }) {
  return (
    <div className="space-y-1 rounded-md border border-emerald-500/50 p-3">
      <div className="flex items-center justify-between">
        <div className="font-medium">Booking {booking.status}</div>
        <Badge variant="outline">SIMULATED</Badge>
      </div>
      <div>{booking.provider.name} · {booking.provider.neighbourhood}</div>
      <div>{when(booking.slot.starts_at)} ({booking.slot.duration_min} min)</div>
      <div className="font-mono text-xs text-muted-foreground">Reference {booking.id}</div>
    </div>
  )
}
