import { createContext, useContext, useState, type ReactNode } from 'react'
import type { ShortlistItem, Slot } from './api'

// What the user picked in the chat (left) so the booking pane (right) can work on it.
export type Selection = { researchJobId: string; item: ShortlistItem; slot: Slot }
type Ctx = { selection: Selection | null; select: (s: Selection) => void }

const SelectionContext = createContext<Ctx>({ selection: null, select: () => {} })
export const useSelection = () => useContext(SelectionContext)

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [selection, select] = useState<Selection | null>(null)
  return <SelectionContext.Provider value={{ selection, select }}>{children}</SelectionContext.Provider>
}
