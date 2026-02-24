'use client'

import { useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { RefreshCw, Loader2 } from 'lucide-react'

interface Props {
  workspaceId: string
}

export default function SyncButton({ workspaceId }: Props) {
  const [isPending, startTransition] = useTransition()
  const router = useRouter()

  const handleSync = () => {
    startTransition(async () => {
      try {
        const res = await fetch('/api/catalog/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ workspace_id: workspaceId }),
        })
        if (!res.ok) throw new Error('Sync failed')
        const data = await res.json()
        toast.success(`Synced ${data.synced ?? 0} products to Merchant Center`)
        router.refresh()
      } catch {
        toast.error('Sync failed — check Merchant Center connection')
      }
    })
  }

  return (
    <button
      onClick={handleSync}
      disabled={isPending}
      className="flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
    >
      {isPending ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <RefreshCw className="h-4 w-4" />
      )}
      Sync to Merchant Center
    </button>
  )
}
