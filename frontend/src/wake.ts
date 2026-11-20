import { useEffect } from 'react'
import { useAui, useAuiState } from '@assistant-ui/react'

// featherweight wakes nothing: the chat turn ended as soon as the research started. When the research ends, the
// application hands the chat the outcome as its next turn. This hook is that application half. The message itself is built
// by the server (`wake` in the job response, only once the job is final); the hook only decides when to send it.

const KEY = 'concierge.woken' // job ids the chat has already been told about
const memory = new Set<string>() // the same, if localStorage is unavailable

const stored = (): string[] => { try { return JSON.parse(localStorage.getItem(KEY) ?? '[]') } catch { return [] } }
const wasWoken = (id: string) => memory.has(id) || stored().includes(id)
const markWoken = (id: string) => {
  memory.add(id)
  try { localStorage.setItem(KEY, JSON.stringify([...stored(), id].slice(-50))) } catch { /* private mode: memory still guards */ }
}

/** Tell the chat, once, how a research it started has ended.
 *  - `enabled` is true only for a research card that belongs to the live conversation. A card restored after a refresh
 *    (the "Last research" panel) must never wake a chat that has no memory of it.
 *  - It waits while the chat is busy, so it never collides with a reply or with something the user is typing.
 *  - A job is marked as woken right before the message is appended, so a re-render or a remount cannot send it twice. */
export function useWake(jobId: string, wake: string | null, enabled: boolean) {
  const aui = useAui()
  const running = useAuiState((s) => s.thread.isRunning)

  useEffect(() => {
    if (!enabled || !wake || running || wasWoken(jobId)) return
    markWoken(jobId)
    aui.thread().append({ role: 'user', content: [{ type: 'text', text: wake }] }) // starts the next turn
  }, [jobId, wake, enabled, running, aui])
}
