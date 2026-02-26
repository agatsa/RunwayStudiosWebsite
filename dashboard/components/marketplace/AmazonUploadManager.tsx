'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Upload, ShoppingBag, Megaphone, Monitor } from 'lucide-react'
import AmazonUploadModal, { AmazonReportType } from './AmazonUploadModal'

const REPORT_TYPES: {
  type: AmazonReportType
  label: string
  icon: React.ReactNode
  color: string
  bg: string
  tip: string
}[] = [
  {
    type: 'sponsored_products',
    label: 'Sponsored Products',
    icon: <ShoppingBag className="h-5 w-5" />,
    color: 'bg-orange-500',
    bg: 'bg-orange-50 border-orange-200',
    tip: 'SP Campaign report',
  },
  {
    type: 'sponsored_brands',
    label: 'Sponsored Brands',
    icon: <Megaphone className="h-5 w-5" />,
    color: 'bg-red-500',
    bg: 'bg-red-50 border-red-200',
    tip: 'SB Campaign report',
  },
  {
    type: 'sponsored_display',
    label: 'Sponsored Display',
    icon: <Monitor className="h-5 w-5" />,
    color: 'bg-pink-500',
    bg: 'bg-pink-50 border-pink-200',
    tip: 'SD Campaign report',
  },
]

export default function AmazonUploadManager({ workspaceId }: { workspaceId: string }) {
  const router = useRouter()
  const [open, setOpen] = useState<AmazonReportType | null>(null)

  return (
    <>
      <div className="rounded-xl border border-gray-100 bg-white p-4">
        <div className="mb-3">
          <h2 className="text-sm font-semibold text-gray-900">Amazon Ads Report Center</h2>
          <p className="text-xs text-gray-500">Upload each ad type report for complete performance visibility</p>
        </div>
        <div className="grid grid-cols-3 gap-3">
          {REPORT_TYPES.map(rt => (
            <button
              key={rt.type}
              onClick={() => setOpen(rt.type)}
              className={`flex flex-col items-center gap-2 rounded-xl border p-4 hover:shadow-md transition-all text-center ${rt.bg}`}
            >
              <div className={`flex h-9 w-9 items-center justify-center rounded-full text-white ${rt.color}`}>
                {rt.icon}
              </div>
              <div>
                <p className="text-xs font-semibold text-gray-800">{rt.label}</p>
                <p className="text-[10px] text-gray-500 mt-0.5">{rt.tip}</p>
              </div>
              <span className="flex items-center gap-1 text-[10px] font-medium text-gray-600">
                <Upload className="h-3 w-3" /> Upload Report
              </span>
            </button>
          ))}
        </div>
      </div>

      {open && (
        <AmazonUploadModal
          workspaceId={workspaceId}
          reportType={open}
          onClose={() => setOpen(null)}
          onSuccess={() => { setOpen(null); router.refresh() }}
        />
      )}
    </>
  )
}
