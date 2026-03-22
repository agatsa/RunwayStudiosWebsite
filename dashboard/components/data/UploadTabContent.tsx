'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Upload, FileSpreadsheet, ExternalLink, CheckCircle2 } from 'lucide-react'
import dynamic from 'next/dynamic'
import type { AmazonReportType } from '@/components/marketplace/AmazonUploadModal'
import type { ReportType as GoogleReportType } from '@/components/google-ads/GoogleAdsReportUploadModal'

const ExcelUploadDialog = dynamic(() => import('@/components/settings/ExcelUploadDialog'), { ssr: false })
const GoogleAdsReportUploadModal = dynamic(() => import('@/components/google-ads/GoogleAdsReportUploadModal'), { ssr: false })
const AmazonUploadModal = dynamic(() => import('@/components/marketplace/AmazonUploadModal'), { ssr: false })

interface UploadCard {
  id: string
  platform: string
  label: string
  description: string
  cadence: string
  color: string
  icon: string
}

const UPLOAD_CARDS: UploadCard[] = [
  {
    id: 'meta',
    platform: 'meta',
    label: 'Meta Ads',
    description: 'Export from Meta Ads Manager → Reports → Campaign performance',
    cadence: 'Weekly (Monday)',
    color: 'blue',
    icon: '📘',
  },
  {
    id: 'google',
    platform: 'google',
    label: 'Google Ads',
    description: 'Export from Google Ads → Reports → Campaign, Ad Group, Keywords, Search Terms',
    cadence: 'Weekly (Monday)',
    color: 'green',
    icon: '🟢',
  },
  {
    id: 'amazon',
    platform: 'amazon',
    label: 'Amazon Ads',
    description: 'Export SP/SB/SD campaign reports from Amazon Ads console',
    cadence: 'Weekly',
    color: 'orange',
    icon: '📦',
  },
]

export default function UploadTabContent({ wsId }: { wsId: string }) {
  const [openDialog, setOpenDialog] = useState<string | null>(null)
  const [successCard, setSuccessCard] = useState<string | null>(null)

  const handleSuccess = (id: string) => {
    setSuccessCard(id)
    setOpenDialog(null)
    setTimeout(() => setSuccessCard(null), 4000)
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-base font-semibold text-gray-900">Upload Ads Reports</h2>
        <p className="mt-1 text-sm text-gray-500">
          Upload your weekly Excel/CSV exports from each platform. ARIA uses this data to power your growth plan, daily briefs, and campaign recommendations.
        </p>
      </div>

      {/* Weekly cadence reminder */}
      <div className="flex items-start gap-3 rounded-xl border border-blue-100 bg-blue-50 p-4">
        <span className="text-lg shrink-0">📅</span>
        <div>
          <p className="text-sm font-semibold text-blue-900">Upload every Monday for best results</p>
          <p className="text-xs text-blue-700 mt-0.5">
            ARIA will send you a WhatsApp + email reminder every Monday at 9am to upload this week&apos;s reports.
            Fresh data = sharper recommendations.
          </p>
        </div>
      </div>

      {/* Upload cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {UPLOAD_CARDS.map(card => (
          <div
            key={card.id}
            className={`rounded-xl border bg-white p-5 transition-all ${
              successCard === card.id ? 'border-green-300 bg-green-50' : 'border-gray-200 hover:border-gray-300'
            }`}
          >
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xl">{card.icon}</span>
              <p className="text-sm font-semibold text-gray-900">{card.label}</p>
              {successCard === card.id && <CheckCircle2 className="h-4 w-4 text-green-500 ml-auto" />}
            </div>
            <p className="text-xs text-gray-500 mb-1">{card.description}</p>
            <p className="text-[11px] text-gray-400 mb-4">Cadence: {card.cadence}</p>
            <button
              onClick={() => setOpenDialog(card.id)}
              className="flex w-full items-center justify-center gap-2 rounded-lg border border-gray-200 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50 transition-colors"
            >
              <Upload className="h-3.5 w-3.5" />
              Upload {card.label} report
            </button>
          </div>
        ))}
      </div>

      {/* How to export guide links */}
      <div className="rounded-xl border border-gray-100 bg-gray-50 p-4">
        <div className="flex items-center gap-2 mb-3">
          <FileSpreadsheet className="h-4 w-4 text-gray-500" />
          <p className="text-sm font-semibold text-gray-700">How to export your reports</p>
        </div>
        <div className="space-y-2 text-xs text-gray-600">
          <div>
            <p className="font-medium text-gray-700">Meta Ads Manager:</p>
            <p>Ads Manager → Campaigns tab → Columns: Performance → Export → .xlsx</p>
          </div>
          <div>
            <p className="font-medium text-gray-700">Google Ads:</p>
            <p>Reports → Predefined reports → Time → Daily → Download CSV</p>
          </div>
          <div>
            <p className="font-medium text-gray-700">Amazon Ads:</p>
            <p>Campaign Manager → Reports → Sponsored Products → Download</p>
          </div>
        </div>
      </div>

      {/* Dialogs */}
      {openDialog === 'meta' && (
        <ExcelUploadDialog
          workspaceId={wsId}
          platform="meta"
          onClose={() => setOpenDialog(null)}
          onSuccess={() => handleSuccess('meta')}
        />
      )}
      {openDialog === 'google' && (
        <GoogleAdsReportUploadModal
          workspaceId={wsId}
          reportType={'campaign' as GoogleReportType}
          onClose={() => setOpenDialog(null)}
          onSuccess={() => handleSuccess('google')}
        />
      )}
      {openDialog === 'amazon' && (
        <AmazonUploadModal
          workspaceId={wsId}
          reportType={'sponsored_products' as AmazonReportType}
          onClose={() => setOpenDialog(null)}
          onSuccess={() => handleSuccess('amazon')}
        />
      )}
    </div>
  )
}
