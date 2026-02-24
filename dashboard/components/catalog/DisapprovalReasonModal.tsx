'use client'

import { useState } from 'react'
import { AlertTriangle, X } from 'lucide-react'
import type { Product } from '@/lib/types'

interface Props {
  product: Product
}

export default function DisapprovalReasonModal({ product }: Props) {
  const [open, setOpen] = useState(false)
  const reasons = product.mc_disapproval_reasons ?? []

  if (reasons.length === 0) return null

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-1 text-xs text-red-600 underline hover:text-red-800"
      >
        <AlertTriangle className="h-3 w-3" />
        {reasons.length} reason{reasons.length > 1 ? 's' : ''}
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-base font-semibold text-gray-900">
                Disapproval Reasons
              </h3>
              <button onClick={() => setOpen(false)} className="text-gray-400 hover:text-gray-600">
                <X className="h-5 w-5" />
              </button>
            </div>
            <p className="mb-3 text-sm font-medium text-gray-700">{product.name}</p>
            <ul className="space-y-2">
              {reasons.map((r, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-red-700">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
                  {r}
                </li>
              ))}
            </ul>
            <button
              onClick={() => setOpen(false)}
              className="mt-5 w-full rounded-lg bg-gray-100 py-2 text-sm font-medium text-gray-700 hover:bg-gray-200"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </>
  )
}
