'use client'

import { useRef, useState } from 'react'
import { X, Upload, FileSpreadsheet, CheckCircle, AlertCircle, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

// ── Types ─────────────────────────────────────────────────────────────────────

type EntityLevel = 'campaign' | 'ad_group' | 'keyword' | 'search_term'

// Common fields all entities may have
type ParsedRow = Record<string, unknown>

interface ParsedSheet {
  entityLevel: EntityLevel
  rows: ParsedRow[]
  entityCount: number  // unique entity names
  hasDateColumn: boolean
}

// ── Column aliases per entity level ──────────────────────────────────────────

type CampaignKey = 'date' | 'campaign_name' | 'spend' | 'impressions' | 'clicks' | 'conversions' | 'revenue'
type AdGroupKey = CampaignKey | 'ad_group_name'
type KeywordKey = AdGroupKey | 'keyword' | 'match_type' | 'quality_score' | 'impression_share'
type SearchTermKey = CampaignKey | 'search_term' | 'keyword' | 'match_type' | 'ad_group_name'

type AnyKey = CampaignKey | AdGroupKey | KeywordKey | SearchTermKey

const BASE_ALIASES: Record<CampaignKey, string[]> = {
  date: ['reporting starts', 'day', 'date'],
  campaign_name: ['campaign name', 'campaign'],
  spend: ['amount spent (inr)', 'amount spent', 'cost', 'spend (inr)', 'spend'],
  // 'impr.' (with dot) matches "Impr." but NOT "Impression share". Bare 'impr' removed —
  // startsWith('impr') would match "Impression share" before "Impressions" in some reports.
  impressions: ['impressions', 'impr.'],
  // 'interactions' added for Google PMax / Display / Video where Google uses "Interactions"
  // as the click-equivalent metric instead of "Clicks".
  clicks: ['link clicks', 'clicks', 'interactions'],
  conversions: ['results', 'conversions', 'conv.'],
  // "conv. value" and "conv value" are what Google Ads exports as the revenue column
  revenue: ['purchase conversion value', 'all conv. value', 'conv. value', 'conv value', 'conversion value (inr)', 'conversion value'],
}

const EXTRA_ALIASES: Partial<Record<AnyKey, string[]>> = {
  ad_group_name: ['ad group name', 'ad group'],
  keyword: ['search keyword', 'keyword'],
  // "search terms match type" is the exact Google Ads column header for keyword match type
  match_type: ['search terms match type', 'match type'],
  quality_score: ['qual. score', 'quality score', 'qs'],
  impression_share: ['search impr. share', 'impr. share', 'impression share'],
  search_term: ['search term', 'query', 'search query'],
}

function detectColumn(headers: string[], key: AnyKey): number {
  const aliases = (BASE_ALIASES as Record<string, string[]>)[key] ?? (EXTRA_ALIASES as Record<string, string[]>)[key] ?? []
  for (const alias of aliases) {
    const idx = headers.findIndex(h => h != null && h.toLowerCase().trim().startsWith(alias))
    if (idx !== -1) return idx
  }
  return -1
}

// ── Sheet type detection ──────────────────────────────────────────────────────

function detectEntityLevel(sheetName: string, headers: string[]): EntityLevel {
  const name = sheetName.toLowerCase()
  if (name.includes('search term') || name.includes('search query')) return 'search_term'
  if (name.includes('keyword')) return 'keyword'
  if (name.includes('ad group')) return 'ad_group'

  // Fallback: detect by column presence
  const h = headers.map(x => x.toLowerCase().trim())
  if (h.some(c => c.startsWith('search term') || c.startsWith('query') || c.startsWith('search query'))) return 'search_term'
  if (h.some(c => c.startsWith('keyword') || c.startsWith('search keyword'))) return 'keyword'
  if (h.some(c => c.startsWith('ad group'))) return 'ad_group'
  return 'campaign'
}

// ── Match type normaliser ─────────────────────────────────────────────────────
// Google Ads exports values like "Broad match", "Exact match (close variant)", etc.

function normalizeMatchType(raw: string): string {
  const lower = raw.toLowerCase().trim()
  if (lower.startsWith('exact')) return 'EXACT'
  if (lower.startsWith('phrase')) return 'PHRASE'
  if (lower.startsWith('broad')) return 'BROAD'
  // Already normalized (EXACT / PHRASE / BROAD)
  const upper = raw.toUpperCase().trim()
  if (upper === 'EXACT' || upper === 'PHRASE' || upper === 'BROAD') return upper
  return 'BROAD'
}

// ── Numeric helper ────────────────────────────────────────────────────────────
// Strip commas before parsing — Google Ads formats large numbers as "4,999.00"

function parseNum(val: unknown): number {
  return parseFloat(String(val ?? 0).replace(/,/g, '')) || 0
}

// ── Date parsing ──────────────────────────────────────────────────────────────

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
    if (a > 1000) return `${a}-${String(b).padStart(2,'0')}-${String(c).padStart(2,'0')}`
    if (c > 1000) return `${c}-${String(b).padStart(2,'0')}-${String(a).padStart(2,'0')}`
  }
  // "January 1, 2026" format
  const m = s.match(/^(\w+)\s+(\d{1,2}),?\s+(\d{4})/)
  if (m) {
    const mon = MONTH_MAP[m[1].toLowerCase()]
    if (mon) return `${m[3]}-${mon}-${String(m[2]).padStart(2, '0')}`
  }
  return null
}

// Scan metadata rows above the header to extract a date range start date
// e.g. "January 1, 2026 - January 31, 2026" → "2026-01-01"
function extractMetadataDate(raw: unknown[][], upToRow: number): string | null {
  for (let i = 0; i < upToRow; i++) {
    const row = raw[i] as unknown[]
    for (const cell of row) {
      const s = String(cell ?? '').trim()
      // Match "Month DD, YYYY" at the start of the cell
      const m = s.match(/^(\w+)\s+(\d{1,2}),?\s+(\d{4})/)
      if (m) {
        const mon = MONTH_MAP[m[1].toLowerCase()]
        if (mon) return `${m[3]}-${mon}-${String(m[2]).padStart(2, '0')}`
      }
    }
  }
  return null
}

// ── Sheet parser ──────────────────────────────────────────────────────────────

function scoreHeaderRow(headers: string[]): number {
  // Count how many recognizable column aliases match this row
  const allKeys: AnyKey[] = [
    'date', 'campaign_name', 'spend', 'impressions', 'clicks', 'conversions', 'revenue',
    'ad_group_name', 'keyword', 'match_type', 'quality_score', 'impression_share', 'search_term',
  ]
  return allKeys.filter(k => detectColumn(headers, k) !== -1).length
}

function parseSheet(sheetName: string, raw: unknown[][]): ParsedSheet | null {
  if (!raw.length) return null

  // Scan up to first 6 rows to find the real header row (most alias matches wins)
  let headerRowIdx = 0
  let bestScore = 0
  for (let i = 0; i < Math.min(6, raw.length); i++) {
    const candidate = (raw[i] as unknown[]).map(h => String(h ?? ''))
    const score = scoreHeaderRow(candidate)
    if (score > bestScore) {
      bestScore = score
      headerRowIdx = i
    }
  }

  const headers = (raw[headerRowIdx] as unknown[]).map(h => String(h ?? ''))
  const entityLevel = detectEntityLevel(sheetName, headers)

  // Build column index map
  const allKeys: AnyKey[] = [
    'date', 'campaign_name', 'spend', 'impressions', 'clicks', 'conversions', 'revenue',
    'ad_group_name', 'keyword', 'match_type', 'quality_score', 'impression_share',
    'search_term',
  ]
  const colIdx: Partial<Record<AnyKey, number>> = {}
  for (const key of allKeys) {
    const idx = detectColumn(headers, key)
    if (idx !== -1) colIdx[key] = idx
  }

  const rows: ParsedRow[] = []
  const entityNames = new Set<string>()
  // Prefer a date extracted from metadata rows (e.g. "January 1, 2026 - January 31, 2026")
  // over today, so aggregate reports are stored under the report period start date
  const fallbackDate = extractMetadataDate(raw, headerRowIdx) ?? new Date().toISOString().slice(0, 10)

  for (let i = headerRowIdx + 1; i < raw.length; i++) {
    const r = raw[i] as unknown[]
    if (!r || r.every(c => c == null || c === '')) continue

    const row: ParsedRow = {}

    // Date — use column value if present, else use date extracted from metadata header
    const rawDate = colIdx.date !== undefined ? r[colIdx.date] : null
    row.date = parseDate(rawDate) ?? fallbackDate

    // Metrics — strip commas before parsing (Google Ads formats "4,999.00")
    row.spend = colIdx.spend !== undefined ? parseNum(r[colIdx.spend]) : 0
    row.impressions = colIdx.impressions !== undefined ? Math.round(parseNum(r[colIdx.impressions])) : 0
    row.clicks = colIdx.clicks !== undefined ? Math.round(parseNum(r[colIdx.clicks])) : 0
    row.conversions = colIdx.conversions !== undefined ? parseNum(r[colIdx.conversions]) : 0
    row.revenue = colIdx.revenue !== undefined ? parseNum(r[colIdx.revenue]) : 0

    // Entity-level specific fields
    if (colIdx.campaign_name !== undefined) {
      row.campaign_name = String(r[colIdx.campaign_name] ?? '').trim()
    }
    if (colIdx.ad_group_name !== undefined) {
      row.ad_group_name = String(r[colIdx.ad_group_name] ?? '').trim()
    }
    if (colIdx.keyword !== undefined) {
      row.keyword = String(r[colIdx.keyword] ?? '').trim()
    }
    if (colIdx.match_type !== undefined) {
      // Normalize "Exact match (close variant)" → "EXACT", "Broad match" → "BROAD" etc.
      row.match_type = normalizeMatchType(String(r[colIdx.match_type] ?? ''))
    }
    if (colIdx.quality_score !== undefined) {
      const qs = r[colIdx.quality_score]
      const qsStr = String(qs ?? '').trim()
      // " --" means Google didn't assign a QS; NaN from parseFloat becomes null via || null
      row.quality_score = qsStr && qsStr !== '--' && qsStr !== ' --' ? parseFloat(qsStr) || null : null
    }
    if (colIdx.impression_share !== undefined) {
      row.impression_share = String(r[colIdx.impression_share] ?? '').replace('%', '').trim()
    }
    if (colIdx.search_term !== undefined) {
      row.search_term = String(r[colIdx.search_term] ?? '').trim()
    }

    // Skip rows with no meaningful entity name
    const mainField = entityLevel === 'search_term' ? row.search_term
      : entityLevel === 'keyword' ? row.keyword
      : entityLevel === 'ad_group' ? row.ad_group_name
      : row.campaign_name
    if (!mainField) continue

    entityNames.add(String(mainField))
    rows.push(row)
  }

  if (!rows.length) return null
  return { entityLevel, rows, entityCount: entityNames.size, hasDateColumn: colIdx.date !== undefined }
}

// ── XLSX template download ────────────────────────────────────────────────────

async function downloadTemplate() {
  const { utils, write } = await import('xlsx')
  const wb = utils.book_new()

  const campaignData = [
    ['Date', 'Campaign Name', 'Spend (INR)', 'Impressions', 'Clicks', 'Conversions', 'Conversion Value (INR)'],
    ['2024-01-01', 'SanketLife Lead Gen', 4200, 18000, 540, 12, 36000],
    ['2024-01-02', 'SanketLife Lead Gen', 3800, 16500, 490, 10, 30000],
    ['2024-01-01', 'EasyTouch Brand', 2100, 9800, 280, 6, 18000],
  ]
  utils.book_append_sheet(wb, utils.aoa_to_sheet(campaignData), 'Campaigns')

  const adGroupData = [
    ['Date', 'Campaign Name', 'Ad Group Name', 'Spend (INR)', 'Impressions', 'Clicks', 'Conversions', 'Conversion Value (INR)'],
    ['2024-01-01', 'SanketLife Lead Gen', 'ECG Machine - Broad', 2200, 9500, 280, 7, 21000],
    ['2024-01-01', 'SanketLife Lead Gen', 'Portable ECG - Exact', 2000, 8500, 260, 5, 15000],
    ['2024-01-01', 'EasyTouch Brand', 'Sugar Monitor', 2100, 9800, 280, 6, 18000],
  ]
  utils.book_append_sheet(wb, utils.aoa_to_sheet(adGroupData), 'Ad Groups')

  const keywordData = [
    ['Date', 'Campaign Name', 'Ad Group Name', 'Keyword', 'Match Type', 'Quality Score', 'Search Impr. Share', 'Spend (INR)', 'Impressions', 'Clicks', 'Conversions', 'Conversion Value (INR)', 'Cost'],
    ['2024-01-01', 'SanketLife Lead Gen', 'ECG Machine - Broad', 'ecg machine', 'BROAD', 6, '32%', 800, 3200, 96, 2, 6000, 8],
    ['2024-01-01', 'SanketLife Lead Gen', 'Portable ECG - Exact', 'portable ecg device', 'EXACT', 9, '68%', 1200, 4200, 148, 5, 15000, 8],
    ['2024-01-01', 'SanketLife Lead Gen', 'ECG Machine - Broad', 'heart monitor', 'BROAD', 4, '15%', 600, 2100, 58, 0, 0, 10],
  ]
  utils.book_append_sheet(wb, utils.aoa_to_sheet(keywordData), 'Keywords')

  const searchTermData = [
    ['Date', 'Search Term', 'Added/Excluded Keyword', 'Match Type', 'Campaign Name', 'Ad Group Name', 'Spend (INR)', 'Impressions', 'Clicks', 'Conversions', 'Conversion Value (INR)'],
    ['2024-01-01', 'buy ecg machine online', 'portable ecg device', 'EXACT', 'SanketLife Lead Gen', 'Portable ECG - Exact', 450, 380, 28, 3, 9000],
    ['2024-01-01', 'ecg machine price india', 'ecg machine', 'BROAD', 'SanketLife Lead Gen', 'ECG Machine - Broad', 320, 280, 19, 1, 3000],
    ['2024-01-01', 'heart rate monitor app', 'heart monitor', 'BROAD', 'SanketLife Lead Gen', 'ECG Machine - Broad', 280, 420, 14, 0, 0],
  ]
  utils.book_append_sheet(wb, utils.aoa_to_sheet(searchTermData), 'Search Terms')

  const buf = write(wb, { bookType: 'xlsx', type: 'array' })
  const blob = new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'kpi_upload_template.xlsx'
  a.click()
  URL.revokeObjectURL(url)
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  workspaceId: string
  platform: 'meta' | 'google'
  onSuccess: () => void
  onClose: () => void
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function ExcelUploadDialog({ workspaceId, platform, onSuccess, onClose }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [step, setStep] = useState<'instructions' | 'preview' | 'uploading' | 'done'>('instructions')
  const [sheets, setSheets] = useState<ParsedSheet[]>([])
  const [parseError, setParseError] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploadProgress, setUploadProgress] = useState<string>('')
  const [totalUpserted, setTotalUpserted] = useState(0)
  const [reportDate, setReportDate] = useState('')

  const platformLabel = platform === 'meta' ? 'Meta Ads Manager' : 'Google Ads'

  async function handleFile(file: File) {
    setParseError(null)
    try {
      const { read, utils } = await import('xlsx')
      const buffer = await file.arrayBuffer()
      const bytes = new Uint8Array(buffer)

      // Google Ads exports CSVs in UTF-16 LE (BOM: FF FE).
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

      const parsedSheets: ParsedSheet[] = []
      const debugLines: string[] = []
      for (const sheetName of wb.SheetNames) {
        const ws = wb.Sheets[sheetName]
        const raw = utils.sheet_to_json(ws, { header: 1, raw: true }) as unknown[][]
        const parsed = parseSheet(sheetName, raw)
        if (parsed) {
          parsedSheets.push(parsed)
        } else if (raw.length > 0) {
          // Collect first non-empty row from each failed sheet for debug
          const firstRow = (raw[0] as unknown[]).map(h => String(h ?? '')).filter(Boolean).slice(0, 6)
          debugLines.push(`Sheet "${sheetName}": found [${firstRow.join(', ')}]`)
        }
      }

      if (!parsedSheets.length) {
        const hint = debugLines.length
          ? `\n\nHeaders found:\n${debugLines.join('\n')}`
          : ''
        setParseError(
          `Could not detect required columns (Campaign Name, Spend, Clicks, etc.) in any sheet.` +
          `\nThe parser scans the first 6 rows for column headers automatically.` +
          hint
        )
        return
      }

      setSheets(parsedSheets)
      setStep('preview')
    } catch (e) {
      setParseError(`Failed to parse file: ${e instanceof Error ? e.message : 'Unknown error'}`)
    }
  }

  const CHUNK_SIZE = 500

  async function handleUpload() {
    setStep('uploading')
    setUploadError(null)
    let total = 0

    const levelOrder: EntityLevel[] = ['campaign', 'ad_group', 'keyword', 'search_term']
    const byLevel: Record<EntityLevel, ParsedRow[]> = {
      campaign: [],
      ad_group: [],
      keyword: [],
      search_term: [],
    }
    for (const sheet of sheets) {
      // If no date column and user specified a report date, override all rows
      const rows = (!sheet.hasDateColumn && reportDate)
        ? sheet.rows.map(r => ({ ...r, date: reportDate }))
        : sheet.rows
      byLevel[sheet.entityLevel].push(...rows)
    }

    try {
      for (const level of levelOrder) {
        const rows = byLevel[level]
        if (!rows.length) continue

        const totalChunks = Math.ceil(rows.length / CHUNK_SIZE)
        for (let i = 0; i < rows.length; i += CHUNK_SIZE) {
          const chunk = rows.slice(i, i + CHUNK_SIZE)
          const chunkNum = Math.floor(i / CHUNK_SIZE) + 1
          if (totalChunks > 1) {
            setUploadProgress(`Uploading ${level.replace('_', ' ')}: chunk ${chunkNum}/${totalChunks}…`)
          } else {
            setUploadProgress(`Uploading ${rows.length} ${level.replace('_', ' ')} rows…`)
          }
          const res = await fetch('/api/upload/excel-kpis', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              workspace_id: workspaceId,
              platform,
              entity_level: level,
              rows: chunk,
            }),
          })
          const data = await res.json()
          if (!res.ok) throw new Error(data.detail ?? `Upload failed for ${level}`)
          total += data.rows_upserted ?? 0
        }
      }

      setTotalUpserted(total)
      toast.success(`${total} rows uploaded successfully`)
      setStep('done')
      onSuccess()
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : 'Upload failed')
      setStep('preview')
    }
  }

  // Summary counts
  const campaignCount = sheets.find(s => s.entityLevel === 'campaign')?.entityCount ?? 0
  const adGroupCount = sheets.find(s => s.entityLevel === 'ad_group')?.entityCount ?? 0
  const keywordCount = sheets.find(s => s.entityLevel === 'keyword')?.entityCount ?? 0
  const searchTermCount = sheets.find(s => s.entityLevel === 'search_term')?.entityCount ?? 0
  const totalRows = sheets.reduce((sum, s) => sum + s.rows.length, 0)

  function summaryText() {
    const parts: string[] = []
    if (campaignCount > 0) parts.push(`${campaignCount} campaign${campaignCount !== 1 ? 's' : ''}`)
    if (adGroupCount > 0) parts.push(`${adGroupCount} ad group${adGroupCount !== 1 ? 's' : ''}`)
    if (keywordCount > 0) parts.push(`${keywordCount} keyword${keywordCount !== 1 ? 's' : ''}`)
    if (searchTermCount > 0) parts.push(`${searchTermCount} search term${searchTermCount !== 1 ? 's' : ''}`)
    return parts.join(' · ')
  }

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm" onClick={onClose} />

      {/* Dialog */}
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="h-5 w-5 text-green-600" />
            <h2 className="text-base font-semibold text-gray-900">Upload {platformLabel} Export</h2>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5">
          {step === 'instructions' && (
            <div className="space-y-4">
              <p className="text-sm text-gray-600">
                Export your campaigns from <strong>{platformLabel}</strong> and upload the file here.
                Supports single-sheet CSV or multi-sheet XLSX with Campaigns, Ad Groups, Keywords, and Search Terms.
              </p>

              <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 text-xs text-gray-600 space-y-1">
                <p className="font-semibold text-gray-700 mb-2">Supported sheets / tabs</p>
                <p>• <strong>Campaigns</strong> — Campaign Name, Spend, Impressions, Clicks, Conversions</p>
                <p>• <strong>Ad Groups</strong> — + Ad Group Name</p>
                <p>• <strong>Keywords</strong> — + Keyword, Match Type, Quality Score, Impr. Share</p>
                <p>• <strong>Search Terms</strong> — Search Term, Added/Excluded Keyword</p>
                <p className="mt-2 text-gray-400">Sheet type is auto-detected by name or column headers.</p>
              </div>

              <button
                onClick={downloadTemplate}
                className="text-xs text-blue-600 underline hover:text-blue-800"
              >
                Download 4-sheet XLSX template
              </button>

              <div
                className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed border-gray-300 p-8 text-center hover:border-blue-400 hover:bg-blue-50 transition-colors"
                onClick={() => inputRef.current?.click()}
              >
                <Upload className="h-8 w-8 text-gray-400" />
                <p className="text-sm font-medium text-gray-700">Click to select file</p>
                <p className="text-xs text-gray-400">.xlsx, .xls, .csv supported</p>
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

          {step === 'preview' && (
            <div className="space-y-4">
              <div className="rounded-xl border border-green-200 bg-green-50 p-4">
                <p className="text-sm font-semibold text-green-800">File parsed successfully</p>
                <p className="mt-1 text-sm text-green-700">
                  {summaryText()} · <strong>{totalRows}</strong> total rows
                </p>
              </div>

              {/* Date picker for aggregate reports (no per-row date column) */}
              {sheets.some(s => !s.hasDateColumn) && (
                <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 space-y-2">
                  <p className="text-xs font-semibold text-amber-800">No date column detected — aggregate report</p>
                  <p className="text-xs text-amber-700">
                    Set the report date so time filters (7d, 30d) work correctly.
                    Without this, all data is stored at today&apos;s date and always appears in every view.
                  </p>
                  <input
                    type="date"
                    value={reportDate}
                    onChange={e => setReportDate(e.target.value)}
                    className="w-full rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-amber-400"
                  />
                  {!reportDate && (
                    <p className="text-xs text-amber-600">Tip: use the last day of the report period (e.g. Jan 31 for a January report).</p>
                  )}
                </div>
              )}

              {/* Per-sheet breakdown */}
              <div className="rounded-xl border border-gray-200 bg-gray-50 p-3 space-y-1.5">
                {sheets.map((s, i) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <span className="text-gray-600 capitalize">{s.entityLevel.replace('_', ' ')}</span>
                    <span className="font-medium text-gray-800">{s.rows.length} rows · {s.entityCount} unique</span>
                  </div>
                ))}
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50 p-3 text-xs text-gray-500 space-y-0.5">
                <p>Data will be saved to your {platform === 'meta' ? 'Meta' : 'Google'} campaigns section.</p>
                <p>Existing live data (if any) is not affected — uploaded data uses a separate marker.</p>
              </div>

              {uploadError && (
                <div className="flex items-start gap-2 rounded-lg bg-red-50 px-3 py-2.5 text-xs text-red-700">
                  <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  {uploadError}
                </div>
              )}

              <div className="flex gap-2 pt-1">
                <button
                  onClick={() => { setSheets([]); setStep('instructions') }}
                  className="flex-1 rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
                >
                  Back
                </button>
                <button
                  onClick={handleUpload}
                  className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
                >
                  Upload {totalRows} rows
                </button>
              </div>
            </div>
          )}

          {step === 'uploading' && (
            <div className="flex flex-col items-center gap-3 py-8">
              <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
              <p className="text-sm text-gray-600">{uploadProgress || `Uploading ${totalRows} rows…`}</p>
            </div>
          )}

          {step === 'done' && (
            <div className="flex flex-col items-center gap-3 py-8">
              <CheckCircle className="h-10 w-10 text-green-500" />
              <p className="text-sm font-medium text-gray-800">Upload complete!</p>
              <p className="text-xs text-gray-500 text-center">
                {totalUpserted} rows saved. Your campaigns will appear in the Campaigns page. Refresh to see them.
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
