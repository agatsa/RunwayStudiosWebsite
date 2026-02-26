import { fetchFromFastAPI } from '@/lib/api'
import ApprovalQueue from '@/components/approvals/ApprovalQueue'
import type { ActionsListResponse } from '@/lib/types'
import { CheckCircle2, XCircle, Clock, Zap } from 'lucide-react'

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

async function fetchStats(workspaceId: string) {
  if (!workspaceId) return null
  try {
    const [pending, approved, all] = await Promise.all([
      fetchActions(workspaceId, 'pending'),
      fetchActions(workspaceId, 'approved'),
      fetchActions(workspaceId, 'all'),
    ])
    const autoExecuted = (all?.actions ?? []).filter(a => a.status === 'executed').length
    return {
      pending: pending?.count ?? 0,
      approved: approved?.count ?? 0,
      autoExecuted,
    }
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

  if (!workspaceId) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border-2 border-dashed border-gray-200">
        <p className="text-gray-500">Select a workspace to view approvals</p>
      </div>
    )
  }

  const [data, stats] = await Promise.all([
    fetchActions(workspaceId, status),
    fetchStats(workspaceId),
  ])

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-gray-900">Decision Inbox</h1>
        <p className="text-sm text-gray-500">AI-detected + manual actions waiting for your approval</p>
      </div>

      {/* Stats strip */}
      {stats && (
        <div className="grid grid-cols-3 gap-3">
          <div className="flex items-center gap-3 rounded-xl border border-yellow-200 bg-yellow-50 px-4 py-3">
            <Clock className="h-5 w-5 text-yellow-600 shrink-0" />
            <div>
              <p className="text-xl font-bold text-yellow-700">{stats.pending}</p>
              <p className="text-xs text-yellow-600">Pending approval</p>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-xl border border-green-200 bg-green-50 px-4 py-3">
            <CheckCircle2 className="h-5 w-5 text-green-600 shrink-0" />
            <div>
              <p className="text-xl font-bold text-green-700">{stats.approved}</p>
              <p className="text-xs text-green-600">Approved this week</p>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3">
            <Zap className="h-5 w-5 text-blue-600 shrink-0" />
            <div>
              <p className="text-xl font-bold text-blue-700">{stats.autoExecuted}</p>
              <p className="text-xs text-blue-600">Auto-executed</p>
            </div>
          </div>
        </div>
      )}

      {/* Filter tabs + count */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">{data?.count ?? 0} actions</p>
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
