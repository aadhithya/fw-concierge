/** The message the application sends the chat when its research ends. The model reads it; the user sees a short notice. */
export const isWake = (text: string) => text.startsWith('<background_result')

export function WakeNotice({ text }: { text: string }) {
  const status = /status="(\w+)"/.exec(text)?.[1]
  return (
    <div className="px-2 text-center text-xs text-muted-foreground">
      {status === 'SUCCESS' ? 'Research finished' : 'Research failed'}: the assistant was told.
    </div>
  )
}
