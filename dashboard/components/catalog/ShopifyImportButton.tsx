'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Download, Loader2, Store, ChevronDown, ChevronUp, CheckCircle, ExternalLink } from 'lucide-react'

interface Props {
  workspaceId: string
  defaultStoreUrl?: string
  shopifyConnected?: boolean
  shopDomain?: string
}

export default function ShopifyImportButton({ workspaceId, defaultStoreUrl = '', shopifyConnected = false, shopDomain = '' }: Props) {
  const [open, setOpen] = useState(false)
  const [storeUrl, setStoreUrl] = useState(defaultStoreUrl)
  const [isPending, startTransition] = useTransition()
  const router = useRouter()

  const handleSync = () => {
    startTransition(async () => {
      try {
        // If Shopify OAuth connected, use the authenticated sync endpoint
        const endpoint = shopifyConnected ? '/api/shopify/sync' : '/api/catalog/import-shopify'
        const body = shopifyConnected
          ? { workspace_id: workspaceId }
          : { workspace_id: workspaceId, store_url: storeUrl.trim() }

        if (!shopifyConnected && !storeUrl.trim()) {
          toast.error('Enter your Shopify store URL')
          return
        }

        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || 'Sync failed')
        const count = data.products_synced ?? data.synced ?? data.count ?? 0
        toast.success(`Synced ${count} products with images from Shopify`)
        setOpen(false)
        router.refresh()
      } catch (e) {
        toast.error(e instanceof Error ? e.message : 'Sync failed')
      }
    })
  }

  if (shopifyConnected) {
    // Compact connected mode — single button, no store URL input needed
    return (
      <div className="relative">
        <button
          onClick={() => setOpen(o => !o)}
          className="flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 px-4 py-2 text-sm font-medium text-green-700 hover:bg-green-100 transition-colors"
        >
          <CheckCircle className="h-4 w-4" />
          Shopify Sync
          {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>

        {open && (
          <div className="absolute right-0 top-full mt-1 z-20 w-72 rounded-xl border border-gray-200 bg-white shadow-lg p-4 space-y-3">
            <div className="flex items-center gap-2">
              <CheckCircle className="h-4 w-4 text-green-500 shrink-0" />
              <div>
                <p className="text-sm font-semibold text-gray-800">Connected</p>
                <p className="text-xs text-gray-500">{shopDomain}</p>
              </div>
            </div>
            <p className="text-xs text-gray-500">
              Re-syncs all products and images from your Shopify store using the Admin API.
              Webhooks keep the catalog updated automatically.
            </p>
            <button
              onClick={handleSync}
              disabled={isPending}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
            >
              {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              {isPending ? 'Syncing…' : 'Full Re-sync'}
            </button>
          </div>
        )}
      </div>
    )
  }

  // Unconnected mode — show URL input + note about Settings
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
          <div className="rounded-lg bg-amber-50 border border-amber-100 px-3 py-2">
            <p className="text-xs text-amber-700">
              For stores behind Cloudflare, connect via{' '}
              <a href="/settings" className="underline font-medium inline-flex items-center gap-0.5">
                Settings <ExternalLink className="h-3 w-3" />
              </a>{' '}
              → Shopify for full Admin API access.
            </p>
          </div>
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
            onClick={handleSync}
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
