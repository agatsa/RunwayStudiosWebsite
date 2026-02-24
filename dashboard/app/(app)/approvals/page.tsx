import { fetchFromFastAPI } from '@/lib/api'
import ApprovalQueue from '@/components/approvals/ApprovalQueue'
import type { ActionsListResponse } from '@/lib/types'

interface PageProps {
  searchParams: { ws?: string; status?: string }
}

async function fetchActions(workspaceId: string, status: string): Promise<ActionsListResponse | null> {
  if (!workspaceId) return null
  try {
    const r = await fetchFromFastAPI(
      `/actions/list?workspace_id=${workspaceId}&status=${status}&limit=100`,
    )
    if (!r.ok) return null
    return r.json()
  } catch {
    return null
  }
}

const STATUS_TABS = [
  { label: 'Pending',  value: 'pending' },
  { label: 'Approved', value: 'approved' },
  { label: 'Rejected', value: 'rejected' },
  { label: 'All',      value: 'all' },
]

export default async function ApprovalsPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''
  const status = searchParams.status ?? 'pending'
  const data = await fetchActions(workspaceId, status)

  if (!workspaceId) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border-2 border-dashed border-gray-200">
        <p className="text-gray-500">Select a workspace to view approvals</p>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Approval Queue</h1>
          <p className="text-sm text-gray-500">{data?.count ?? 0} actions</p>
        </div>
        {/* Status filter tabs */}
        <div className="flex gap-1 rounded-lg border border-gray-200 bg-white p-1">
          {STATUS_TABS.map(({ label, value }) => (
            <a
              key={value}
              href={`/approvals?ws=${workspaceId}&status=${value}`}
              className={`rounded px-3 py-1.5 text-sm font-medium transition-colors ${
                status === value
                  ? 'bg-gray-900 text-white'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              {label}
            </a>
          ))}
        </div>
      </div>

      <ApprovalQueue actions={data?.actions ?? []} />
    </div>
  )
}
