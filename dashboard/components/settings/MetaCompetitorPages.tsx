'use client'

import { useEffect, useState, useRef } from 'react'
import { Plus, Trash2, Loader2, Megaphone } from 'lucide-react'
import { toast } from 'sonner'

interface Page {
  page_name: string
  added_at: string
}

/**
 * If the user pastes a Facebook URL, extract the page handle.
 * e.g. https://www.facebook.com/ultrahumanhq/ → "ultrahumanhq"
 * Otherwise return the trimmed input as-is (brand name).
 */
function parseFacebookInput(raw: string): string {
  const trimmed = raw.trim()
  try {
    const url = new URL(trimmed)
    const host = url.hostname.replace(/^www\./, '')
    if (host === 'facebook.com' || host === 'fb.com' || host === 'm.facebook.com') {
      // pathname is like /ultrahumanhq or /ultrahumanhq/
      const handle = url.pathname.replace(/^\//, '').replace(/\/$/, '').split('/')[0]
      if (handle && handle !== 'pages' && handle !== 'profile') return handle
    }
  } catch {
    // not a URL — use as typed
  }
  return trimmed
}

export default function MetaCompetitorPages({ workspaceId }: { workspaceId: string }) {
  const [pages, setPages] = useState<Page[]>([])
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // Live preview of what will actually be stored
  const parsed = parseFacebookInput(input)
  const isFbUrl = input.trim().startsWith('http') && parsed !== input.trim()

  const load = async () => {
    try {
      const r = await fetch(`/api/meta/competitor-pages?workspace_id=${workspaceId}`)
      if (r.ok) {
        const d = await r.json()
        setPages(d.pages ?? [])
      }
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => { load() }, [workspaceId])

  const handleAdd = async () => {
    const name = parsed
    if (!name) return
    if (pages.some(p => p.page_name.toLowerCase() === name.toLowerCase())) {
      toast.error('Already in your list')
      return
    }
    setAdding(true)
    try {
      const r = await fetch('/api/meta/competitor-pages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, page_name: name }),
      })
      if (!r.ok) throw new Error('Failed')
      setPages(prev => [...prev, { page_name: name, added_at: new Date().toISOString() }])
      setInput('')
      toast.success(`Added "${name}" to Meta competitor list`)
      inputRef.current?.focus()
    } catch {
      toast.error('Failed to add competitor')
    }
    setAdding(false)
  }

  const handleDelete = async (pageName: string) => {
    setDeleting(pageName)
    try {
      const r = await fetch('/api/meta/competitor-pages', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, page_name: pageName }),
      })
      if (!r.ok) throw new Error('Failed')
      setPages(prev => prev.filter(p => p.page_name !== pageName))
      toast.success(`Removed "${pageName}"`)
    } catch {
      toast.error('Failed to remove competitor')
    }
    setDeleting(null)
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="flex items-center gap-2 mb-1">
        <Megaphone className="h-4 w-4 text-blue-500" />
        <p className="text-sm font-semibold text-gray-800">Meta Ad Library Competitors</p>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Paste a Facebook page URL <span className="text-gray-400">(facebook.com/brand)</span> or
        type a brand name. We track their active ads on Facebook &amp; Instagram.
      </p>

      {/* Input row */}
      <div className="flex gap-2 mb-1">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleAdd()}
          placeholder="facebook.com/ultrahumanhq or Ultrahuman"
          className="flex-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs focus:border-blue-400 focus:outline-none"
        />
        <button
          onClick={handleAdd}
          disabled={adding || !input.trim()}
          className="flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {adding ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
          Add
        </button>
      </div>

      {/* Live parse preview */}
      {isFbUrl && parsed && (
        <p className="mb-2 text-[10px] text-blue-600">
          Will be saved as: <strong>{parsed}</strong>
        </p>
      )}

      {/* List */}
      <div className="mt-2">
        {loading ? (
          <div className="space-y-1.5">
            {[1, 2].map(i => (
              <div key={i} className="h-7 rounded bg-gray-100 animate-pulse" />
            ))}
          </div>
        ) : pages.length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-3">
            No competitors added yet.
          </p>
        ) : (
          <div className="space-y-1.5">
            {pages.map(p => (
              <div
                key={p.page_name}
                className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-1.5"
              >
                <span className="flex-1 text-xs text-gray-700 truncate">{p.page_name}</span>
                <button
                  onClick={() => handleDelete(p.page_name)}
                  disabled={deleting === p.page_name}
                  className="text-gray-300 hover:text-red-500 disabled:opacity-50"
                >
                  {deleting === p.page_name
                    ? <Loader2 className="h-3 w-3 animate-spin" />
                    : <Trash2 className="h-3 w-3" />}
                </button>
              </div>
            ))}
            <p className="pt-1 text-[10px] text-gray-400">
              Competitor Intel → Meta Ad Library → Sync now to fetch their active ads.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
