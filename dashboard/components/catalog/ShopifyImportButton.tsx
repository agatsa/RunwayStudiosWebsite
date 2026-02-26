'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Download, Loader2, Store, ChevronDown, ChevronUp } from 'lucide-react'

interface Props {
  workspaceId: string
  defaultStoreUrl?: string
}

export default function ShopifyImportButton({ workspaceId, defaultStoreUrl = '' }: Props) {
  const [open, setOpen] = useState(false)
  const [storeUrl, setStoreUrl] = useState(defaultStoreUrl)
  const [isPending, startTransition] = useTransition()
  const router = useRouter()

  const handleImport = () => {
    const url = storeUrl.trim()
    if (!url) { toast.error('Enter your Shopify store URL'); return }
    startTransition(async () => {
      try {
        const res = await fetch('/api/catalog/import-shopify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ workspace_id: workspaceId, store_url: url }),
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || 'Import failed')
        toast.success(`Imported ${data.synced ?? data.count ?? 0} products with images from Shopify`)
        setOpen(false)
        router.refresh()
      } catch (e) {
        toast.error(e instanceof Error ? e.message : 'Import failed')
      }
    })
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-100 transition-colors"
      >
        <Store className="h-4 w-4" />
        Import from Shopify
        {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-20 w-80 rounded-xl border border-gray-200 bg-white shadow-lg p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-800">Import Products from Shopify</p>
          <p className="text-xs text-gray-500">
            Pulls all products + images from your store into the catalog.
            Used by Campaign Planner for creative generation.
          </p>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Store URL</label>
            <input
              value={storeUrl}
              onChange={e => setStoreUrl(e.target.value)}
              placeholder="agatsaone.com or yourstore.myshopify.com"
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none"
            />
          </div>
          <button
            onClick={handleImport}
            disabled={isPending || !storeUrl.trim()}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            {isPending ? 'Importing…' : 'Import Products & Images'}
          </button>
        </div>
      )}
    </div>
  )
}
