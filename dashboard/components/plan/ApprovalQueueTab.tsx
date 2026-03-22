'use client'

import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import ApprovalQueue from '@/components/approvals/ApprovalQueue'
import type { ActionRow } from '@/lib/types'

export default function ApprovalQueueTab({ wsId }: { wsId: string }) {
  const [actions, setActions] = useState<ActionRow[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`/api/actions/list?workspace_id=${wsId}&status=pending&limit=100`)
      .then(r => r.ok ? r.json() : null)
      .then(d => setActions(d?.actions ?? []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [wsId])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
      </div>
    )
  }

  return <ApprovalQueue actions={actions} />
}
