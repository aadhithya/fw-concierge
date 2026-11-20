import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'

// Demo controls. They are plain parameters: each is sent along with the request that starts the work it affects, so nothing is
// stored on the server. The delay goes to the chat (and to Retry research), the failure flag to Prepare booking (and its Retry).
export type Controls = { sleepSeconds: number; simulateFailure: boolean }

const KEY = 'concierge.controls'
const DEFAULT: Controls = { sleepSeconds: 4, simulateFailure: false }
const load = (): Controls => { try { return { ...DEFAULT, ...JSON.parse(localStorage.getItem(KEY) ?? '{}') } } catch { return DEFAULT } }

const ControlsContext = createContext<{ controls: Controls; set: (change: Partial<Controls>) => void }>({ controls: DEFAULT, set: () => {} })
export const useControls = () => useContext(ControlsContext)

export function ControlsProvider({ children }: { children: ReactNode }) {
  const [controls, setControls] = useState<Controls>(load)
  useEffect(() => { try { localStorage.setItem(KEY, JSON.stringify(controls)) } catch { /* private mode: fine */ } }, [controls])
  return <ControlsContext.Provider value={{ controls, set: (change) => setControls((c) => ({ ...c, ...change })) }}>{children}</ControlsContext.Provider>
}

/** A small card of demo controls, at the bottom of the right-hand pane. */
export function ControlsPane() {
  const { controls, set } = useControls()
  return (
    <Card size="sm" className="w-full">
      <CardHeader><CardTitle className="text-sm">Demo controls</CardTitle></CardHeader>
      <CardContent className="space-y-4 text-xs text-muted-foreground">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span>Provider service delay (the MCP tool sleeps)</span>
            <span className="font-mono text-foreground">{controls.sleepSeconds} s</span>
          </div>
          <Slider min={0} max={20} step={1} value={[controls.sleepSeconds]} onValueChange={(v) => set({ sleepSeconds: Array.isArray(v) ? v[0] : v })} />
          <div>Applies to the next research.</div>
        </div>
        <label className="flex items-center justify-between gap-3">
          <span>Fail the booking preparation after its first step<br />(Retry then resumes it)</span>
          <Switch checked={controls.simulateFailure} onCheckedChange={(on) => set({ simulateFailure: on })} />
        </label>
      </CardContent>
    </Card>
  )
}
