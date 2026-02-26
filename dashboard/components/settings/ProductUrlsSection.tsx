'use client'

import { useState, useEffect, useCallback } from 'react'
import { Plus, Loader2, Trash2, ExternalLink, RefreshCw, ImageOff } from 'lucide-react'
import { toast } from 'sonner'

interface ScrapedProduct {
  id: string
  name: string
  price_inr: number | null
  images: { url: string; alt: string }[]
  product_url: string | null
  source_platform: string
  last_synced_at?: string
}

interface Props {
  workspaceId: string
}

export default function ProductUrlsSection({ workspaceId }: Props) {
  const [products, setProducts] = useState<ScrapedProduct[]>([])
  const [loading, setLoading] = useState(true)
  const [urlInput, setUrlInput] = useState('')
  const [scraping, setScraping] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [rescrapingId, setRescrapingId] = useState<string | null>(null)

  const fetchScrapedProducts = useCallback(async () => {
    if (!workspaceId) return
    try {
      const r = await fetch(`/api/catalog/products?workspace_id=${workspaceId}`)
      if (!r.ok) return
      const data = await r.json()
      const scraped = (data.products ?? []).filter(
        (p: ScrapedProduct) => p.source_platform === 'scraped'
      )
      setProducts(scraped)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [workspaceId])

  useEffect(() => {
    fetchScrapedProducts()
  }, [fetchScrapedProducts])

  const handleScrape = async (url?: string) => {
    const targetUrl = (url ?? urlInput).trim()
    if (!targetUrl) {
      toast.error('Enter a product page URL')
      return
    }
    if (!targetUrl.startsWith('http')) {
      toast.error('URL must start with http or https')
      return
    }

    if (url) {
      setRescrapingId(products.find(p => p.product_url === url)?.id ?? null)
    } else {
      setScraping(true)
    }

    try {
      const res = await fetch('/api/catalog/scrape-url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, url: targetUrl }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? 'Scrape failed')
      toast.success(`Scraped "${data.product?.name}" — added to catalog`)
      setUrlInput('')
      await fetchScrapedProducts()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Scrape failed')
    } finally {
      setScraping(false)
      setRescrapingId(null)
    }
  }

  const handleDelete = async (product: ScrapedProduct) => {
    if (!confirm(`Remove "${product.name}" from your catalog?`)) return
    setDeletingId(product.id)
    try {
      const res = await fetch(
        `/api/catalog/product/${product.id}?workspace_id=${workspaceId}`,
        { method: 'DELETE' }
      )
      if (!res.ok) throw new Error('Delete failed')
      toast.success(`"${product.name}" removed`)
      setProducts(prev => prev.filter(p => p.id !== product.id))
    } catch {
      toast.error('Failed to remove product')
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 space-y-4">
      <div>
        <p className="text-sm font-semibold text-gray-800">Your Product URLs</p>
        <p className="text-xs text-gray-500 mt-0.5">
          Paste any product page URL — we&apos;ll scrape the name, images, and price automatically.
        </p>
      </div>

      {/* URL input */}
      <div className="flex gap-2">
        <input
          value={urlInput}
          onChange={e => setUrlInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleScrape() }}
          placeholder="https://agatsaone.com/products/sanketlife-2-0"
          className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none"
        />
        <button
          onClick={() => handleScrape()}
          disabled={scraping || !urlInput.trim()}
          className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {scraping ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
          {scraping ? 'Scraping…' : 'Add'}
        </button>
      </div>

      {/* Product list */}
      {loading ? (
        <div className="flex items-center gap-2 py-3 text-xs text-gray-400">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading…
        </div>
      ) : products.length === 0 ? (
        <div className="rounded-lg bg-gray-50 px-4 py-6 text-center">
          <p className="text-xs text-gray-400">No product URLs added yet.</p>
          <p className="text-xs text-gray-400 mt-0.5">Add a URL above to scrape product data into your catalog.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {products.map(product => {
            const thumb = product.images?.[0]?.url
            const isDeleting = deletingId === product.id
            const isRescraping = rescrapingId === product.id
            return (
              <div
                key={product.id}
                className="flex items-center gap-3 rounded-lg border border-gray-100 bg-gray-50 px-3 py-2"
              >
                {/* Thumbnail */}
                <div className="h-10 w-10 shrink-0 rounded-md overflow-hidden bg-gray-200">
                  {thumb ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={thumb}
                      alt={product.name}
                      className="h-full w-full object-cover"
                      onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center">
                      <ImageOff className="h-4 w-4 text-gray-400" />
                    </div>
                  )}
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-gray-800 truncate">{product.name}</p>
                  <p className="text-[10px] text-gray-400 truncate">
                    {product.product_url}
                    {product.price_inr ? ` · ₹${product.price_inr.toLocaleString('en-IN')}` : ''}
                  </p>
                </div>

                {/* Actions */}
                <div className="flex shrink-0 items-center gap-1">
                  {product.product_url && (
                    <a
                      href={product.product_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100"
                      title="Open URL"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  )}
                  <button
                    onClick={() => product.product_url && handleScrape(product.product_url)}
                    disabled={isRescraping || isDeleting}
                    className="rounded p-1 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 disabled:opacity-40"
                    title="Re-scrape"
                  >
                    {isRescraping
                      ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      : <RefreshCw className="h-3.5 w-3.5" />}
                  </button>
                  <button
                    onClick={() => handleDelete(product)}
                    disabled={isDeleting || isRescraping}
                    className="rounded p-1 text-gray-400 hover:text-red-600 hover:bg-red-50 disabled:opacity-40"
                    title="Remove"
                  >
                    {isDeleting
                      ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      : <Trash2 className="h-3.5 w-3.5" />}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
