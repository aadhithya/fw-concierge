import { useEffect } from 'react'
import { useAui, useAuiState } from '@assistant-ui/react'
import { getJob } from './api'

// featherweight wakes nothing: the chat turn ended as soon as the research started. When the research ends, the
// application hands the chat the outcome as its next turn. This hook is that application half. The message itself is built
// by the server (`wake` in the job response, only once the job is final); the hook only decides when to send it. Right before
// sending, it asks the server again: a turn that was still working when the job ended may have received the result already.

const KEY = 'concierge.woken' // job ids the chat has already been told about
const memory = new Set<string>() // the same, if localStorage is unavailable

const stored = (): string[] => { try { return JSON.parse(localStorage.getItem(KEY) ?? '[]') } catch { return [] } }
const wasWoken = (id: string) => memory.has(id) || stored().includes(id)
const unmark = (id: string) => {
  memory.delete(id)
  try { localStorage.setItem(KEY, JSON.stringify(stored().filter((x) => x !== id))) } catch { /* private mode */ }
}
const markWoken = (id: string) => {
  memory.add(id)
  try { localStorage.setItem(KEY, JSON.stringify([...stored(), id].slice(-50))) } catch { /* private mode: memory still guards */ }
}

/** Tell the chat, once, how a research it started has ended.
 *  - `enabled` is true only for a research card that belongs to the live conversation. A card restored after a refresh
 *    (the "Last research" panel) must never wake a chat that has no memory of it.
 *  - It waits while the chat is busy, so it never collides with a reply or with something the user is typing.
 *  - It then reads the job again. No `wake` any more means a chat turn already got the result: nothing is sent.
 *  - A job is marked as woken before that read, so a re-render or a remount cannot send it twice. If the chat became busy
 *    in the meantime, the mark is removed and the wake waits for the next quiet moment. */
export function useWake(jobId: string, wake: string | null, enabled: boolean) {
  const aui = useAui()
  const running = useAuiState((s) => s.thread.isRunning)

  useEffect(() => {
    if (!enabled || !wake || running || wasWoken(jobId)) return
    markWoken(jobId)
    getJob(jobId)
      .then((job) => {
        if (!job.wake) return // the chat already has this result
        if (aui.thread().getState().isRunning) return unmark(jobId) // busy again: try when it is quiet
        aui.thread().append({ role: 'user', content: [{ type: 'text', text: job.wake }] }) // starts the next turn
      })
      .catch(() => unmark(jobId)) // could not read the job: try again on the next change
  }, [jobId, wake, enabled, running, aui])
}
