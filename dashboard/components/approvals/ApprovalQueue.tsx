import ApprovalRow from './ApprovalRow'
import type { ActionRow } from '@/lib/types'

interface Props {
  actions: ActionRow[]
}

export default function ApprovalQueue({ actions }: Props) {
  if (actions.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-xl border-2 border-dashed border-gray-200">
        <div className="text-center">
          <p className="text-sm font-medium text-gray-500">All clear — no pending actions</p>
          <p className="text-xs text-gray-400 mt-1">Actions from AI analysis and anomaly detection will appear here</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {actions.map(a => (
        <ApprovalRow key={a.id} action={a} />
      ))}
    </div>
  )
}
