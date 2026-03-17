/**
 * Renders a string that may contain **bold** markdown as HTML.
 * Usage: <BoldText text={aiGeneratedString} />
 */
export default function BoldText({ text, className }: { text: string; className?: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g)
  return (
    <span className={className}>
      {parts.map((part, i) =>
        i % 2 === 1 ? <strong key={i}>{part}</strong> : part
      )}
    </span>
  )
}
