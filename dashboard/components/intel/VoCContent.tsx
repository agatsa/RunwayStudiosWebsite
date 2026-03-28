'use client'

import { useState, useEffect } from 'react'
import { Search, MessageCircle, TrendingUp, Loader2, ChevronRight, ExternalLink, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'

interface RedditPost {
  title: string
  subreddit: string
  score: number
  url: string
  text_preview: string
  num_comments: number
  created_utc: number
}

interface VoCScan {
  scan_id: string
  query: string
  summary: string
  post_count: number
  credits_used: number
  created_at: string
}

interface VoCResult {
  scan_id: string
  query: string
  posts: RedditPost[]
  summary: string
  credits_used: number
  credit_balance: number
}

interface Props {
  wsId: string
}

export default function VoCContent({ wsId }: Props) {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<VoCResult | null>(null)
  const [history, setHistory] = useState<VoCScan[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [error, setError] = useState('')
  const [activePost, setActivePost] = useState<RedditPost | null>(null)

  useEffect(() => {
    if (!wsId) return
    setHistoryLoading(true)
    fetch(`/api/intel/voc/history?workspace_id=${wsId}`)
      .then(r => r.json())
      .then(d => setHistory(d.history ?? []))
      .catch(() => {})
      .finally(() => setHistoryLoading(false))
  }, [wsId])

  const handleSearch = async () => {
    if (!query.trim() || loading) return
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const r = await fetch('/api/intel/voc/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: wsId, query: query.trim(), limit: 25 }),
      })
      const data = await r.json()
      if (!r.ok) {
        if (data.detail?.includes('Insufficient credits') || r.status === 402) {
          setError('Not enough credits. You need 3 credits for a VoC search.')
        } else {
          setError(data.detail ?? 'Search failed. Please try again.')
        }
        return
      }
      setResult(data)
      setHistory(prev => [{
        scan_id: data.scan_id,
        query: data.query,
        summary: data.summary,
        post_count: data.posts.length,
        credits_used: data.credits_used,
        created_at: new Date().toISOString(),
      }, ...prev.slice(0, 19)])
    } catch {
      setError('Failed to connect. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const formatSummary = (text: string) => {
    return text.split('\n').map((line, i) => {
      if (line.startsWith('**') && line.endsWith('**')) {
        return <p key={i} className="font-semibold text-gray-900 mt-3 first:mt-0">{line.replace(/\*\*/g, '')}</p>
      }
      if (line.startsWith('**')) {
        const parts = line.split('**')
        return (
          <p key={i} className="mt-2">
            <span className="font-semibold text-gray-900">{parts[1]}</span>
            <span className="text-gray-700">{parts[2] ?? ''}</span>
          </p>
        )
      }
      if (line.startsWith('- ') || line.startsWith('• ')) {
        return <li key={i} className="ml-4 text-gray-700 list-disc">{line.slice(2)}</li>
      }
      if (!line.trim()) return null
      return <p key={i} className="text-gray-700">{line}</p>
    }).filter(Boolean)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-base font-semibold text-gray-900">Voice of Customer</h2>
        <p className="text-sm text-gray-500 mt-0.5">
          Mine Reddit for what real customers say about your brand, competitors, or product category.
        </p>
      </div>

      {/* Search bar */}
      <div className="rounded-xl border border-gray-200 bg-white p-4 space-y-3">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder='e.g. "portable ECG monitor" or "blood glucose monitor India"'
              className="w-full pl-9 pr-4 py-2.5 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
            />
          </div>
          <button
            onClick={handleSearch}
            disabled={!query.trim() || loading}
            className="flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50 transition-colors whitespace-nowrap"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            {loading ? 'Searching…' : 'Search · 3 credits'}
          </button>
        </div>
        <p className="text-xs text-gray-400">
          Searches Reddit discussions. Uses 3 credits per search.
        </p>
        {error && (
          <p className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>
        )}
      </div>

      {/* Results */}
      {result && (
        <div className="space-y-4">
          {/* Summary */}
          <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-4">
            <div className="flex items-center gap-2 mb-3">
              <TrendingUp className="h-4 w-4 text-indigo-600" />
              <span className="text-sm font-semibold text-indigo-900">AI Summary — {result.posts.length} discussions analysed</span>
              <span className="ml-auto text-xs text-indigo-500">{result.credits_used} credits used</span>
            </div>
            <div className="text-sm space-y-1">
              {formatSummary(result.summary)}
            </div>
          </div>

          {/* Posts grid */}
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-2">
              Reddit Discussions ({result.posts.length})
            </h3>
            <div className="space-y-2">
              {result.posts.map((post, i) => (
                <div
                  key={i}
                  className={cn(
                    'rounded-lg border bg-white p-3 cursor-pointer hover:border-indigo-200 hover:bg-indigo-50/30 transition-colors',
                    activePost?.url === post.url ? 'border-indigo-300 bg-indigo-50' : 'border-gray-200'
                  )}
                  onClick={() => setActivePost(activePost?.url === post.url ? null : post)}
                >
                  <div className="flex items-start gap-2">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900 leading-snug line-clamp-2">{post.title}</p>
                      <div className="flex items-center gap-3 mt-1">
                        <span className="text-xs text-indigo-600 font-medium">{post.subreddit}</span>
                        <span className="text-xs text-gray-400">{post.score.toLocaleString()} upvotes</span>
                        <span className="text-xs text-gray-400">{post.num_comments} comments</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <a
                        href={post.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={e => e.stopPropagation()}
                        className="p-1 rounded hover:bg-gray-100"
                      >
                        <ExternalLink className="h-3.5 w-3.5 text-gray-400" />
                      </a>
                      <ChevronRight className={cn(
                        'h-3.5 w-3.5 text-gray-400 transition-transform',
                        activePost?.url === post.url && 'rotate-90'
                      )} />
                    </div>
                  </div>
                  {activePost?.url === post.url && post.text_preview && (
                    <p className="mt-2 text-xs text-gray-600 border-t border-indigo-100 pt-2">
                      {post.text_preview}
                      {post.text_preview.length >= 300 && '…'}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* History */}
      {!result && (
        <div>
          <h3 className="text-sm font-medium text-gray-700 mb-3">Past Searches</h3>
          {historyLoading ? (
            <div className="flex items-center gap-2 text-sm text-gray-400 py-4">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading history…
            </div>
          ) : history.length === 0 ? (
            <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 p-8 text-center">
              <MessageCircle className="h-8 w-8 text-gray-300 mx-auto mb-2" />
              <p className="text-sm text-gray-500">No searches yet.</p>
              <p className="text-xs text-gray-400 mt-1">Search for your brand name or a product category to get started.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {history.map(scan => (
                <button
                  key={scan.scan_id}
                  onClick={() => setQuery(scan.query)}
                  className="w-full rounded-lg border border-gray-200 bg-white p-3 text-left hover:border-brand-200 hover:bg-brand-50/30 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <Search className="h-3.5 w-3.5 text-gray-400 shrink-0" />
                    <span className="text-sm font-medium text-gray-800 flex-1 truncate">{scan.query}</span>
                    <span className="text-xs text-gray-400">{scan.post_count} posts</span>
                    <span className="text-xs text-gray-400 flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {new Date(scan.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  {scan.summary && (
                    <p className="text-xs text-gray-500 mt-1.5 line-clamp-2 ml-5">{scan.summary.slice(0, 120)}…</p>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
