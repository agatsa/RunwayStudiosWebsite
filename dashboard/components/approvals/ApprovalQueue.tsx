import ApprovalRow from './ApprovalRow'
import type { ActionRow } from '@/lib/types'

interface Props {
  actions: ActionRow[]
}

export default function ApprovalQueue({ actions }: Props) {
  if (actions.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-xl border-2 border-dashed border-gray-200">
        <p className="text-sm text-gray-400">No pending actions</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
      <table className="w-full text-sm">
        <thead className="border-b border-gray-200 bg-gray-50">
          <tr>
            <th className="py-3 pr-4 pl-4 text-left text-xs font-medium uppercase text-gray-500">Platform</th>
            <th className="py-3 pr-4 text-left text-xs font-medium uppercase text-gray-500">Action</th>
            <th className="py-3 pr-4 text-left text-xs font-medium uppercase text-gray-500">Change</th>
            <th className="py-3 pr-4 text-left text-xs font-medium uppercase text-gray-500">Triggered</th>
            <th className="py-3 pr-4 text-left text-xs font-medium uppercase text-gray-500">Status</th>
            <th className="py-3 text-left text-xs font-medium uppercase text-gray-500">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 pl-4">
          {actions.map(a => (
            <ApprovalRow key={a.id} action={a} />
          ))}
        </tbody>
      </table>
    </div>
  )
}
