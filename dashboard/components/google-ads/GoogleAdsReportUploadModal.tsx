'use client'

import { useRef, useState } from 'react'
import { X, Upload, FileSpreadsheet, CheckCircle, AlertCircle, Loader2 } from 'lucide-react'

// ── Types ────────────────────────────────────────────────────────────────────

export type ReportType = 'campaign' | 'keyword' | 'search_term' | 'geo' | 'device' | 'hour_of_day' | 'asset' | 'auction_insight' | 'auction_insight_shopping'

type ParsedRow = Record<string, unknown>

interface ParseResult {
  rows: ParsedRow[]
  entityCount: number
}

// ── Report config per type ────────────────────────────────────────────────────

interface ReportConfig {
  label: string
  endpoint: string
  entityLevelParam: string | null   // null = auction_insight uses its own field
  description: string
  // Column aliases used to detect + extract values
  aliases: Record<string, string[]>
  // Which alias key is the "main entity" (used for dedup count + skip-if-empty)
  mainKey: string
}

const BASE_ALIASES: Record<string, string[]> = {
  date:          ['reporting starts', 'day', 'date'],
  campaign_name: ['campaign name', 'campaign'],
  spend:         ['amount spent (inr)', 'amount spent', 'cost', 'spend (inr)', 'spend'],
  impressions:   ['impressions', 'impr.', 'impr'],
  clicks:        ['link clicks', 'clicks'],
  conversions:   ['results', 'conversions', 'conv.'],
  revenue:       ['purchase conversion value', 'all conv. value', 'conv. value', 'conv value', 'conversion value (inr)', 'conversion value'],
}

const REPORT_CONFIGS: Record<ReportType, ReportConfig> = {
  campaign: {
    label: 'Campaign Report',
    endpoint: '/api/upload/excel-kpis',
    entityLevelParam: 'campaign',
    description: 'Campaign Name, Spend, Impressions, Clicks, Conversions, Conv. Value',
    mainKey: 'campaign_name',
    aliases: { ...BASE_ALIASES },
  },
  keyword: {
    label: 'Keywords Report',
    endpoint: '/api/upload/excel-kpis',
    entityLevelParam: 'keyword',
    description: 'Keyword, Match Type, Quality Score, Campaign Name, Spend, Conversions',
    mainKey: 'keyword',
    aliases: {
      ...BASE_ALIASES,
      ad_group_name:    ['ad group name', 'ad group'],
      keyword:          ['search keyword', 'keyword'],
      match_type:       ['search terms match type', 'match type'],
      quality_score:    ['qual. score', 'quality score', 'qs'],
      impression_share: ['search impr. share', 'impr. share', 'impression share'],
    },
  },
  search_term: {
    label: 'Search Terms Report',
    endpoint: '/api/upload/excel-kpis',
    entityLevelParam: 'search_term',
    description: 'Search Term, Added/Excluded Keyword, Match Type, Campaign Name, Spend',
    mainKey: 'search_term',
    aliases: {
      ...BASE_ALIASES,
      search_term:   ['search term', 'query', 'search query'],
      keyword:       ['added/excluded keyword', 'search keyword', 'keyword'],
      match_type:    ['search terms match type', 'match type'],
      ad_group_name: ['ad group name', 'ad group'],
    },
  },
  geo: {
    label: 'Geographic Report',
    endpoint: '/api/upload/excel-kpis',
    entityLevelParam: 'geo',
    description: 'Location/City/Region, Campaign Name, Spend, Impressions, Interactions/Clicks, Conversions',
    mainKey: 'region',
    aliases: {
      ...BASE_ALIASES,
      clicks:  ['interactions', 'link clicks', 'clicks'],   // Location report uses "Interactions"
      region:  ['location', 'city', 'region', 'country/territory', 'most specific location'],
    },
  },
  device: {
    label: 'Device Report',
    endpoint: '/api/upload/excel-kpis',
    entityLevelParam: 'device',
    description: 'Device, Campaign Name, Spend, Impressions, Clicks, Conversions',
    mainKey: 'device',
    aliases: {
      ...BASE_ALIASES,
      device: ['device', 'device type'],
    },
  },
  hour_of_day: {
    label: 'Time of Day Report',
    endpoint: '/api/upload/excel-kpis',
    entityLevelParam: 'hour_of_day',
    description: 'Hour of Day, Day of Week, Campaign Name, Spend, Conversions',
    mainKey: 'hour',
    aliases: {
      ...BASE_ALIASES,
      hour:        ['hour of day', 'hour'],
      day_of_week: ['day of week', 'day'],
    },
  },
  asset: {
    label: 'Ad Assets Report (RSA)',
    endpoint: '/api/upload/excel-kpis',
    entityLevelParam: 'asset',
    description: 'Asset Text, Asset Type, Performance Label, Campaign, Impressions, Clicks',
    mainKey: 'asset_text',
    aliases: {
      date:              ['reporting starts', 'day', 'date'],
      campaign_name:     ['campaign name', 'campaign'],
      ad_group_name:     ['ad group name', 'ad group'],
      impressions:       ['impressions'],
      clicks:            ['link clicks', 'clicks'],
      asset_text:        ['asset text', 'asset', 'headline', 'description', 'asset value'],
      asset_type:        ['asset type', 'type'],
      performance_label: ['performance label', 'label', 'performance'],
    },
  },
  auction_insight: {
    label: 'Search Auction Insights',
    endpoint: '/api/upload/auction-insights',
    entityLevelParam: null,
    description: 'Display URL Domain, Impression Share, Overlap Rate, Position Above Rate, Top of Page Rate',
    mainKey: 'competitor_domain',
    aliases: {
      date:                   ['reporting starts', 'day', 'date'],
      campaign_name:          ['campaign name', 'campaign'],
      competitor_domain:      ['display url domain', 'competitor domain', 'competitor (domain)', 'domain'],
      impression_share:       ['impression share', 'impr. share', 'search impr. share'],
      overlap_rate:           ['overlap rate'],
      position_above_rate:    ['position above rate'],
      top_of_page_rate:       ['top of page rate', 'top-of-page rate'],
      abs_top_impression_pct: ['abs. top of page rate', 'absolute top of page rate'],
      outranking_share:       ['outranking share'],
    },
  },
  auction_insight_shopping: {
    label: 'Shopping Auction Insights',
    endpoint: '/api/upload/auction-insights',
    entityLevelParam: null,
    description: 'Store Display Name, Impression Share, Overlap Rate, Outranking Share',
    mainKey: 'competitor_domain',
    aliases: {
      date:             ['reporting starts', 'day', 'date'],
      campaign_name:    ['campaign name', 'campaign'],
      competitor_domain: ['store display name', 'store name', 'competitor domain', 'competitor (domain)', 'domain'],
      impression_share: ['impression share', 'impr. share'],
      overlap_rate:     ['overlap rate'],
      outranking_share: ['outranking share'],
    },
  },
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const MONTH_MAP: Record<string, string> = {
  january: '01', february: '02', march: '03', april: '04', may: '05', june: '06',
  july: '07', august: '08', september: '09', october: '10', november: '11', december: '12',
  jan: '01', feb: '02', mar: '03', apr: '04', jun: '06', jul: '07', aug: '08',
  sep: '09', oct: '10', nov: '11', dec: '12',
}

function parseDate(raw: unknown): string | null {
  if (raw == null) return null
  if (typeof raw === 'number') {
    const ms = (raw - 25569) * 86400000
    return new Date(ms).toISOString().slice(0, 10)
  }
  const s = String(raw).trim()
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 10)
  const parts = s.split(/[\/\-]/)
  if (parts.length === 3) {
    const [a, b, c] = parts.map(Number)
    if (a > 1000) return `${a}-${String(b).padStart(2, '0')}-${String(c).padStart(2, '0')}`
    if (c > 1000) return `${c}-${String(b).padStart(2, '0')}-${String(a).padStart(2, '0')}`
  }
  const m = s.match(/^(\w+)\s+(\d{1,2}),?\s+(\d{4})/)
  if (m) {
    const mon = MONTH_MAP[m[1].toLowerCase()]
    if (mon) return `${m[3]}-${mon}-${String(m[2]).padStart(2, '0')}`
  }
  return null
}

function parseNum(val: unknown): number {
  return parseFloat(String(val ?? 0).replace(/,/g, '').replace('%', '')) || 0
}

function detectCol(headers: string[], aliases: string[]): number {
  for (const alias of aliases) {
    const idx = headers.findIndex(h => h != null && h.toLowerCase().trim().startsWith(alias.toLowerCase()))
    if (idx !== -1) return idx
  }
  return -1
}

function extractMetadataDate(raw: unknown[][], upToRow: number): string | null {
  for (let i = 0; i < upToRow; i++) {
    const row = raw[i] as unknown[]
    for (const cell of row) {
      const s = String(cell ?? '').trim()
      const m = s.match(/^(\w+)\s+(\d{1,2}),?\s+(\d{4})/)
      if (m) {
        const mon = MONTH_MAP[m[1].toLowerCase()]
        if (mon) return `${m[3]}-${mon}-${String(m[2]).padStart(2, '0')}`
      }
    }
  }
  return null
}

// Score a candidate header row by how many aliases match
function scoreRow(row: string[], allAliases: Record<string, string[]>): number {
  return Object.values(allAliases).filter(aliases => detectCol(row, aliases) !== -1).length
}

function parseSheet(config: ReportConfig, raw: unknown[][]): ParseResult | null {
  if (!raw.length) return null
  const allAliases = config.aliases

  // Find best header row in first 6 rows
  let headerRowIdx = 0
  let bestScore = 0
  for (let i = 0; i < Math.min(6, raw.length); i++) {
    const candidate = (raw[i] as unknown[]).map(h => String(h ?? ''))
    const score = scoreRow(candidate, allAliases)
    if (score > bestScore) { bestScore = score; headerRowIdx = i }
  }
  if (bestScore === 0) return null

  const headers = (raw[headerRowIdx] as unknown[]).map(h => String(h ?? ''))

  // Build colIdx map
  const colIdx: Record<string, number> = {}
  for (const [key, aliases] of Object.entries(allAliases)) {
    const idx = detectCol(headers, aliases)
    if (idx !== -1) colIdx[key] = idx
  }

  const fallbackDate = extractMetadataDate(raw, headerRowIdx) ?? new Date().toISOString().slice(0, 10)
  const rows: ParsedRow[] = []
  const entityNames = new Set<string>()

  for (let i = headerRowIdx + 1; i < raw.length; i++) {
    const r = raw[i] as unknown[]
    if (!r || r.every(c => c == null || c === '')) continue

    const row: ParsedRow = {}

    // Date
    const rawDate = colIdx.date !== undefined ? r[colIdx.date] : null
    row.date = parseDate(rawDate) ?? fallbackDate

    // Standard numeric fields
    for (const field of ['spend', 'impressions', 'clicks', 'conversions', 'revenue']) {
      if (colIdx[field] !== undefined) {
        const val = parseNum(r[colIdx[field]])
        row[field] = field === 'impressions' || field === 'clicks' ? Math.round(val) : val
      }
    }

    // All string fields
    for (const field of [
      'campaign_name', 'ad_group_name', 'keyword', 'match_type', 'search_term',
      'region', 'device', 'day_of_week', 'asset_text', 'asset_type', 'performance_label',
      'competitor_domain',
    ]) {
      if (colIdx[field] !== undefined) {
        row[field] = String(r[colIdx[field]] ?? '').trim()
      }
    }

    // Hour as integer
    if (colIdx.hour !== undefined) {
      row.hour = Math.round(parseNum(r[colIdx.hour]))
    }

    // Percentage fields for auction insights
    for (const field of [
      'impression_share', 'overlap_rate', 'position_above_rate',
      'top_of_page_rate', 'abs_top_impression_pct', 'outranking_share',
    ]) {
      if (colIdx[field] !== undefined) {
        row[field] = String(r[colIdx[field]] ?? '').trim()
      }
    }

    // Quality score
    if (colIdx.quality_score !== undefined) {
      const qs = String(r[colIdx.quality_score] ?? '').trim()
      row.quality_score = qs && qs !== '--' && qs !== ' --' ? parseFloat(qs) || null : null
    }

    // Impression share for keywords
    if (colIdx.impression_share !== undefined && config.entityLevelParam === 'keyword') {
      row.impression_share = String(r[colIdx.impression_share] ?? '').replace('%', '').trim()
    }

    // Normalize match type
    if (row.match_type) {
      const mt = String(row.match_type).toLowerCase()
      if (mt.startsWith('exact')) row.match_type = 'EXACT'
      else if (mt.startsWith('phrase')) row.match_type = 'PHRASE'
      else row.match_type = 'BROAD'
    }

    // Skip if main entity missing
    const mainVal = String(row[config.mainKey] ?? '').trim()
    if (!mainVal) continue

    entityNames.add(mainVal)
    rows.push(row)
  }

  if (!rows.length) return null
  return { rows, entityCount: entityNames.size }
}

// ── Chunked upload helper ─────────────────────────────────────────────────────

const CHUNK_SIZE = 500

async function uploadChunked(
  endpoint: string,
  baseBody: Record<string, unknown>,
  rows: ParsedRow[],
  onProgress: (msg: string) => void,
): Promise<number> {
  let total = 0
  const totalChunks = Math.ceil(rows.length / CHUNK_SIZE)

  for (let i = 0; i < rows.length; i += CHUNK_SIZE) {
    const chunk = rows.slice(i, i + CHUNK_SIZE)
    const chunkNum = Math.floor(i / CHUNK_SIZE) + 1
    onProgress(`Uploading chunk ${chunkNum}/${totalChunks} (${chunk.length} rows)…`)

    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...baseBody, rows: chunk }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail ?? `Upload failed (chunk ${chunkNum})`)
    total += data.rows_upserted ?? chunk.length
  }
  return total
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  reportType: ReportType
  workspaceId: string
  onSuccess: () => void
  onClose: () => void
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function GoogleAdsReportUploadModal({ reportType, workspaceId, onSuccess, onClose }: Props) {
  const config = REPORT_CONFIGS[reportType]
  const inputRef = useRef<HTMLInputElement>(null)
  const [step, setStep] = useState<'instructions' | 'preview' | 'uploading' | 'done'>('instructions')
  const [result, setResult] = useState<ParseResult | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [progress, setProgress] = useState('')
  const [totalUpserted, setTotalUpserted] = useState(0)

  async function handleFile(file: File) {
    setParseError(null)
    try {
      const { read, utils } = await import('xlsx')
      const buffer = await file.arrayBuffer()
      const bytes = new Uint8Array(buffer)

      // Google Ads exports CSVs in UTF-16 LE (BOM: FF FE).
      // Pass as decoded string so xlsx doesn't misinterpret the encoding.
      let wb
      if (bytes[0] === 0xFF && bytes[1] === 0xFE) {
        const text = new TextDecoder('utf-16le').decode(buffer)
        wb = read(text, { type: 'string', cellDates: false })
      } else if (bytes[0] === 0xFE && bytes[1] === 0xFF) {
        const text = new TextDecoder('utf-16be').decode(buffer)
        wb = read(text, { type: 'string', cellDates: false })
      } else {
        wb = read(buffer, { type: 'array', cellDates: false })
      }

      let best: ParseResult | null = null
      const debugLines: string[] = []

      for (const sheetName of wb.SheetNames) {
        const ws = wb.Sheets[sheetName]
        const raw = utils.sheet_to_json(ws, { header: 1, raw: true }) as unknown[][]
        const parsed = parseSheet(config, raw)
        if (parsed && parsed.rows.length > (best?.rows.length ?? 0)) {
          best = parsed
        } else if (!parsed && raw.length > 0) {
          const firstRow = (raw[0] as unknown[]).map(h => String(h ?? '')).filter(Boolean).slice(0, 6)
          debugLines.push(`Sheet "${sheetName}": [${firstRow.join(', ')}]`)
        }
      }

      if (!best) {
        const hint = debugLines.length ? `\n\nHeaders found:\n${debugLines.join('\n')}` : ''
        setParseError(
          `Could not detect required columns for ${config.label}.\n` +
          `Expected: ${config.description}` + hint,
        )
        return
      }

      setResult(best)
      setStep('preview')
    } catch (e) {
      setParseError(`Failed to parse file: ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  async function handleUpload() {
    if (!result) return
    setStep('uploading')
    setUploadError(null)

    try {
      const baseBody: Record<string, unknown> = { workspace_id: workspaceId, platform: 'google' }
      if (config.entityLevelParam) {
        baseBody.entity_level = config.entityLevelParam
      }

      const upserted = await uploadChunked(config.endpoint, baseBody, result.rows, setProgress)
      setTotalUpserted(upserted)
      setStep('done')
      onSuccess()
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : 'Upload failed')
      setStep('preview')
    }
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="h-5 w-5 text-blue-600" />
            <h2 className="text-base font-semibold text-gray-900">Upload {config.label}</h2>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5">
          {step === 'instructions' && (
            <div className="space-y-4">
              <div className="rounded-xl border border-blue-100 bg-blue-50 p-4 text-xs text-blue-800">
                <p className="font-semibold mb-1">Required columns</p>
                <p>{config.description}</p>
                <p className="mt-2 text-blue-600">Column names are auto-detected — exact match not required.</p>
              </div>

              <div
                className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed border-gray-300 p-8 text-center hover:border-blue-400 hover:bg-blue-50 transition-colors"
                onClick={() => inputRef.current?.click()}
              >
                <Upload className="h-8 w-8 text-gray-400" />
                <p className="text-sm font-medium text-gray-700">Click to select file</p>
                <p className="text-xs text-gray-400">.xlsx, .xls, .csv supported · Large files OK (chunked upload)</p>
              </div>

              {parseError && (
                <div className="flex items-start gap-2 rounded-lg bg-red-50 px-3 py-2.5 text-xs text-red-700">
                  <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <pre className="whitespace-pre-wrap">{parseError}</pre>
                </div>
              )}

              <input
                ref={inputRef}
                type="file"
                accept=".xlsx,.xls,.csv"
                className="hidden"
                onChange={e => {
                  const f = e.target.files?.[0]
                  if (f) handleFile(f)
                  e.target.value = ''
                }}
              />
            </div>
          )}

          {step === 'preview' && result && (
            <div className="space-y-4">
              <div className="rounded-xl border border-green-200 bg-green-50 p-4">
                <p className="text-sm font-semibold text-green-800">File parsed successfully</p>
                <p className="mt-1 text-sm text-green-700">
                  <strong>{result.rows.length.toLocaleString()}</strong> rows · <strong>{result.entityCount}</strong> unique {config.mainKey.replace('_', ' ')}s
                </p>
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50 p-3 text-xs text-gray-500 space-y-0.5">
                <p>Data will be upserted — re-uploading the same report replaces previous values.</p>
                {result.rows.length > CHUNK_SIZE && (
                  <p className="text-blue-600">Large file: will upload in {Math.ceil(result.rows.length / CHUNK_SIZE)} chunks of {CHUNK_SIZE} rows.</p>
                )}
              </div>

              {uploadError && (
                <div className="flex items-start gap-2 rounded-lg bg-red-50 px-3 py-2.5 text-xs text-red-700">
                  <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  {uploadError}
                </div>
              )}

              <div className="flex gap-2 pt-1">
                <button
                  onClick={() => { setResult(null); setStep('instructions') }}
                  className="flex-1 rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
                >
                  Back
                </button>
                <button
                  onClick={handleUpload}
                  className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
                >
                  Upload {result.rows.length.toLocaleString()} rows
                </button>
              </div>
            </div>
          )}

          {step === 'uploading' && (
            <div className="flex flex-col items-center gap-3 py-8">
              <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
              <p className="text-sm text-gray-600">{progress || 'Uploading…'}</p>
              <div className="w-full rounded-full bg-gray-100 h-1.5">
                <div className="h-1.5 rounded-full bg-blue-500 animate-pulse w-full" />
              </div>
            </div>
          )}

          {step === 'done' && (
            <div className="flex flex-col items-center gap-3 py-8">
              <CheckCircle className="h-10 w-10 text-green-500" />
              <p className="text-sm font-medium text-gray-800">Upload complete!</p>
              <p className="text-xs text-gray-500 text-center">
                {totalUpserted.toLocaleString()} rows saved. Refresh the page to see updated charts.
              </p>
              <button
                onClick={onClose}
                className="mt-2 rounded-lg bg-gray-900 px-6 py-2 text-sm font-medium text-white hover:bg-gray-700"
              >
                Done
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
