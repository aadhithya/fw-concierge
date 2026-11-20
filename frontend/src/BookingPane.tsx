import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { book, getPreparation, retryPreparation, startPreparation, when, type Booking, type Preparation, type Slot } from './api'
import { useControls } from './controls'
import { useSelection, type Selection } from './selection'

const STATE_STYLE: Record<string, string> = {
  queued: 'bg-zinc-700 text-zinc-100', running: 'bg-blue-600/80 text-white',
  completed: 'bg-emerald-600/80 text-white', failed: 'bg-red-600/80 text-white',
}
const DAY = (d: Date) => d.toLocaleDateString('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric' })
const HOUR = (iso: string) => new Date(iso).toLocaleTimeString('en-GB', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit' })

/** The right half: the booking flow for the slot picked in the chat. */
export function BookingPane() {
  const { selection } = useSelection()
  if (!selection) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
        Pick a slot from the shortlist in the chat to prepare and confirm a (simulated) booking.
      </div>
    )
  }
  // keyed: choosing another slot starts the flow afresh
  return <Flow key={selection.researchJobId + selection.slot.id} selection={selection} />
}

function Flow({ selection }: { selection: Selection }) {
  const { item, slot, researchJobId } = selection
  const { controls } = useControls()
  const [prepId, setPrepId] = useState<string | null>(null)
  const [state, setState] = useState<string>('queued')
  const [lines, setLines] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<Preparation | null>(null)
  const [booking, setBooking] = useState<Booking | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [idempotencyKey] = useState(() => crypto.randomUUID()) // a repeated click sends the same key: one booking

  // The job's status arrives over SSE: each progress line and each state change is applied as it happens.
  useEffect(() => {
    if (!prepId) return
    setLines([]); setState('queued'); setFailure(null)
    const events = new EventSource(`/api/jobs/${prepId}/stream`)
    events.addEventListener('progress', (e) => setLines((l) => [...l, JSON.parse((e as MessageEvent).data).message]))
    events.addEventListener('state', (e) => {
      const next = JSON.parse((e as MessageEvent).data).state as string
      setState(next)
      if (next === 'completed' || next === 'failed') {
        events.close()
        getPreparation(prepId).then((p) => { setResult(p.result); setFailure(p.error) }).catch(() => {})
      }
    })
    events.onerror = () => events.close()
    return () => events.close()
  }, [prepId])

  const run = (start: () => Promise<{ job_id: string }>) => { setError(null); setResult(null); start().then((r) => setPrepId(r.job_id)).catch((e) => setError(e.message)) }
  const confirm = () => book(researchJobId, item.provider.id, slot.id, idempotencyKey).then(setBooking).catch((e) => setError(e.message))

  return (
    <div className="space-y-4 p-4 text-sm">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Your booking</h2>
        <Badge variant="outline">SIMULATED</Badge>
      </div>

      <div className="rounded-md border p-3">
        <div className="font-medium">{item.provider.name}</div>
        <div className="text-xs text-muted-foreground">{item.provider.neighbourhood} · {item.provider.description}</div>
        <div className="mt-2 font-medium">{when(slot.starts_at)} · {slot.duration_min} min</div>
      </div>

      <WeekCalendar offered={item.slots} selected={slot} />

      {booking ? (
        <div className="space-y-1 rounded-md border border-emerald-500/50 p-3">
          <div className="font-medium">Booking {booking.status}</div>
          <div>{booking.provider.name} · {when(booking.slot.starts_at)}</div>
          <div className="font-mono text-xs text-muted-foreground">Reference {booking.id}</div>
          <div className="text-xs text-muted-foreground">Simulated: no real appointment was made.</div>
        </div>
      ) : (
        <>
          {!prepId && <Button onClick={() => run(() => startPreparation(researchJobId, item.provider.id, slot.id, controls.simulateFailure))}>Prepare booking</Button>}

          {prepId && (
            <div className="space-y-2 rounded-md border p-3">
              <div className="flex items-center justify-between">
                <span className="font-medium">Preparing your booking</span>
                <Badge className={STATE_STYLE[state]}>{state}</Badge>
              </div>
              <ul className="space-y-0.5 text-xs text-muted-foreground">{lines.map((l, i) => <li key={i}>· {l}</li>)}</ul>

              {state === 'failed' && (
                <div className="space-y-2">
                  <div className="text-red-400">It failed ({failure ?? 'error'}) after the first step. Retrying resumes the job: the finished step is reused.</div>
                  <Button size="sm" onClick={() => run(() => retryPreparation(prepId, controls.simulateFailure))}>Retry</Button>
                </div>
              )}
              {state === 'completed' && result && (
                <div className="space-y-3">
                  <p>{result.confirmation}</p>
                  {result.briefing.concerns.length > 0 && <p className="text-xs text-amber-400">Note: {result.briefing.concerns.join('; ')}</p>}
                  <p className="text-xs text-muted-foreground">Nothing is booked until you confirm.</p>
                  <Button onClick={confirm}>Confirm booking</Button>
                </div>
              )}
            </div>
          )}
        </>
      )}
      {error && <div className="text-red-400">{error}</div>}
    </div>
  )
}

/** A dummy week view: the provider's offered times as pills, the chosen one highlighted. Not a real calendar. */
function WeekCalendar({ offered, selected }: { offered: Slot[]; selected: Slot }) {
  const day = new Date(selected.starts_at)
  const monday = new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate() - ((day.getUTCDay() + 6) % 7)))
  const days = Array.from({ length: 7 }, (_, i) => new Date(monday.getTime() + i * 86400000))
  const key = (d: Date) => d.toISOString().slice(0, 10)
  return (
    <div className="grid grid-cols-7 gap-1 text-center text-xs">
      {days.map((d) => (
        <div key={key(d)} className="min-h-20 rounded-md border p-1">
          <div className="mb-1 text-muted-foreground">{DAY(d)}</div>
          {offered.filter((s) => s.starts_at.slice(0, 10) === key(d)).map((s) => (
            <div key={s.id} className={`mb-0.5 rounded px-1 py-0.5 ${s.id === selected.id ? 'bg-primary text-primary-foreground' : 'bg-muted'}`}>
              {HOUR(s.starts_at)}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}
