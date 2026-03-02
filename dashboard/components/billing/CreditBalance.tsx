'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Zap } from 'lucide-react'
import type { BillingStatus } from '@/lib/types'

interface Props {
  wsId: string
}

export default function CreditBalance({ wsId }: Props) {
  const [balance, setBalance] = useState<number | null>(null)

  useEffect(() => {
    if (!wsId) return
    const load = async () => {
      try {
        const res = await fetch(`/api/billing/status?workspace_id=${wsId}`)
        if (res.ok) {
          const data: BillingStatus = await res.json()
          setBalance(data.credit_balance)
        }
      } catch { /* ignore */ }
    }
    load()
    const id = setInterval(load, 60_000)
    return () => clearInterval(id)
  }, [wsId])

  if (balance === null) return null

  return (
    <Link
      href={`/billing?ws=${wsId}`}
      className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs hover:bg-gray-50 transition-colors group"
    >
      <Zap className="h-3 w-3 text-amber-400 shrink-0" />
      <span className="font-semibold text-gray-700 group-hover:text-gray-900">{balance}</span>
      <span className="text-gray-400">credits</span>
    </Link>
  )
}
