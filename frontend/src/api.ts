// The only way the UI talks to the backend: application-owned HTTP endpoints. No featherweight internals.
export type Slot = { id: string; provider_id: string; starts_at: string; duration_min: number }
export type Provider = {
  id: string; name: string; neighbourhood: string; description: string; price_band: number
  languages: string[]; accessible: boolean; home_visits: boolean; evenings: boolean; weekends: boolean
}
export type ShortlistItem = {
  rank: number; provider: Provider; slots: Slot[]
  reasons: string[] // written by the model
  fit: string; matched: string[]; concerns: string[]
}
export type Booking = { id: string; status: string; simulated: boolean; provider: Provider; slot: Slot; job_id: string }
export type Job = {
  job_id: string
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  error: string | null
  criteria: { location: string; date_from: string; date_to: string; preferences: string[] } | null
  result: { summary: string; considered: number; shortlist: ShortlistItem[] } | null
  booking: Booking | null
  progress: { seq: number; message: string }[]
  wake: string | null // once the job is final: the message the chat should be told (built by the server)
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { headers: { 'content-type': 'application/json' }, ...init })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText)
  return res.json()
}

export type Preparation = {
  provider: Provider; slot: Slot
  briefing: { matches: string[]; concerns: string[]; before_you_go: string[] } // model-written
  confirmation: string // model-written
}
export type PreparationState = {
  job_id: string; state: Job['state']; error: string | null; result: Preparation | null
  progress: { seq: number; message: string }[]
}
export const startPreparation = (job_id: string, provider_id: string, slot_id: string) =>
  call<{ job_id: string }>('/api/preparations', { method: 'POST', body: JSON.stringify({ job_id, provider_id, slot_id }) })
export const getPreparation = (id: string) => call<PreparationState>(`/api/preparations/${id}`)
export const retryPreparation = (id: string) => call<{ job_id: string }>(`/api/preparations/${id}/retry`, { method: 'POST' })

export const getJob = (id: string) => call<Job>(`/api/jobs/${id}`)
export const retryJob = (id: string) => call<{ job_id: string }>(`/api/jobs/${id}/retry`, { method: 'POST' })
export const getOutage = () => call<{ enabled: boolean }>('/api/demo/outage')
export const setOutage = (enabled: boolean) =>
  call('/api/demo/outage', { method: 'PUT', body: JSON.stringify({ enabled }) })
export const book = (job_id: string, provider_id: string, slot_id: string, idempotency_key: string) =>
  call<Booking>('/api/bookings', { method: 'POST', body: JSON.stringify({ job_id, provider_id, slot_id, idempotency_key }) })

// Slot times are the region's local time (stored as UTC), so show them as they are.
export const when = (iso: string) =>
  new Date(iso).toLocaleString('en-GB', {
    timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })
