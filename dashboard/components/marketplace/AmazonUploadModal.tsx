'use client'

import { useRef, useState } from 'react'
import { Upload, X, CheckCircle, AlertCircle, Loader2, ChevronDown, ChevronUp } from 'lucide-react'
import * as XLSX from 'xlsx'

// ── column aliases ────────────────────────────────────────────────────────────
const ALIASES: Record<string, string[]> = {
  campaign_name:   ['campaign name', 'campaign', 'name'],
  spend:           ['spend', 'cost', 'total spend'],
  impressions:     ['impressions', 'impr.', 'impr'],
  clicks:          ['clicks'],
  orders:          ['7 day total orders (#)', '14 day total orders (#)', '7 day total orders', '14 day total orders', 'total orders (#)', 'total orders', 'orders', 'purchases'],
  sales:           ['7 day total sales', '14 day total sales', 'total sales', 'ordered product sales', 'sales', 'revenue', '7 day total sales (#)'],
  acos:            ['total advertising cost of sales (acos)', 'acos %', 'acos', 'advertising cost of sales'],
  roas:            ['total return on advertising spend (roas)', 'roas'],
  campaign_status: ['status', 'campaign status', 'state'],
  ad_type:         ['type', 'ad type', 'campaign type', 'targeting type'],
  date:            ['date', 'day', 'start date'],
}

function normalise(header: string): string {
  return header.toLowerCase().replace(/[^a-z0-9 ]/g, '').trim()
}

function mapHeaders(headers: string[]): Record<string, number> {
  const map: Record<string, number> = {}
  for (const [field, aliases] of Object.entries(ALIASES)) {
    for (let i = 0; i < headers.length; i++) {
      const h = normalise(headers[i])
      if (aliases.some(a => h === a || h.includes(a))) {
        if (!(field in map)) map[field] = i
      }
    }
  }
  return map
}

function parseNum(v: unknown): number {
  if (v == null) return 0
  const s = String(v).replace(/,/g, '').replace(/%/g, '').replace(/₹/g, '').replace(/\$/g, '').trim()
  if (s === '--' || s === '' || s.toLowerCase() === 'n/a') return 0
  return parseFloat(s) || 0
}

function findHeaderRow(sheet: XLSX.WorkSheet): { headers: string[], startRow: number } {
  const range = XLSX.utils.decode_range(sheet['!ref'] || 'A1:Z100')
  for (let r = range.s.r; r <= Math.min(range.s.r + 6, range.e.r); r++) {
    const row: string[] = []
    for (let c = range.s.c; c <= range.e.c; c++) {
      const cell = sheet[XLSX.utils.encode_cell({ r, c })]
      row.push(cell ? String(cell.v ?? '') : '')
    }
    const filled = row.filter(v => v.trim().length > 0)
    if (filled.length >= 4) return { headers: row, startRow: r + 1 }
  }
  return { headers: [], startRow: 1 }
}

// ── report type configs ───────────────────────────────────────────────────────
export type AmazonReportType = 'sponsored_products' | 'sponsored_brands' | 'sponsored_display'

const REPORT_CONFIGS = {
  sponsored_products: {
    label: 'Sponsored Products',
    color: 'bg-orange-500',
    desc: 'Campaign or Search Term report from Amazon Ads console',
    tip: 'Download from: Amazon Ads → Reports → Sponsored Products → Campaign',
  },
  sponsored_brands: {
    label: 'Sponsored Brands',
    color: 'bg-red-500',
    desc: 'Sponsored Brands campaign performance report',
    tip: 'Download from: Amazon Ads → Reports → Sponsored Brands → Campaign',
  },
  sponsored_display: {
    label: 'Sponsored Display',
    color: 'bg-pink-500',
    desc: 'Display campaign performance report',
    tip: 'Download from: Amazon Ads → Reports → Sponsored Display → Campaign',
  },
}

// ── component ─────────────────────────────────────────────────────────────────
interface Props {
  workspaceId: string
  reportType: AmazonReportType
  onClose: () => void
  onSuccess: () => void
}

const CHUNK = 500

export default function AmazonUploadModal({ workspaceId, reportType, onClose, onSuccess }: Props) {
  const cfg = REPORT_CONFIGS[reportType]
  const fileRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [fileName, setFileName] = useState('')
  const [parseError, setParseError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [done, setDone] = useState(false)
  const [showTip, setShowTip] = useState(false)

  function parseFile(file: File) {
    setParseError('')
    setRows([])
    setFileName(file.name)
    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const data = new Uint8Array(e.target!.result as ArrayBuffer)
        const wb = XLSX.read(data, { type: 'array', codepage: 65001 })
        const ws = wb.Sheets[wb.SheetNames[0]]
        const { headers, startRow } = findHeaderRow(ws)
        if (!headers.length) { setParseError('Could not find header row.'); return }
        const colMap = mapHeaders(headers)
        if (!('campaign_name' in colMap) && !('spend' in colMap)) {
          setParseError(`Could not detect campaign data. Headers found: ${headers.filter(h=>h).join(', ')}`)
          return
        }
        const range = XLSX.utils.decode_range(ws['!ref'] || 'A1:Z1')
        const parsed: Record<string, unknown>[] = []
        for (let r = startRow; r <= range.e.r; r++) {
          const get = (field: string) => {
            const ci = colMap[field]
            if (ci == null) return undefined
            const cell = ws[XLSX.utils.encode_cell({ r, c: ci })]
            return cell ? cell.v : undefined
          }
          const campaignName = String(get('campaign_name') ?? '').trim()
          if (!campaignName) continue
          parsed.push({
            campaign_name:   campaignName,
            spend:           parseNum(get('spend')),
            impressions:     parseNum(get('impressions')),
            clicks:          parseNum(get('clicks')),
            orders:          parseNum(get('orders')),
            sales:           parseNum(get('sales')),
            acos:            parseNum(get('acos')),
            roas:            parseNum(get('roas')),
            campaign_status: String(get('campaign_status') ?? 'ENABLED').toUpperCase(),
            ad_type:         String(get('ad_type') ?? cfg.label).trim() || cfg.label,
            date:            get('date') ? String(get('date')).trim() : '',
          })
        }
        if (!parsed.length) { setParseError('No data rows found after header.'); return }
        setRows(parsed)
      } catch (err) {
        setParseError(`Parse error: ${err}`)
      }
    }
    reader.readAsArrayBuffer(file)
  }

  async function handleUpload() {
    if (!rows.length) return
    setUploading(true)
    setProgress(0)
    let uploaded = 0
    try {
      for (let i = 0; i < rows.length; i += CHUNK) {
        const chunk = rows.slice(i, i + CHUNK)
        const res = await fetch('/api/marketplace/upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ workspace_id: workspaceId, rows: chunk, ad_type: cfg.label }),
        })
        if (!res.ok) throw new Error(await res.text())
        uploaded += chunk.length
        setProgress(Math.round((uploaded / rows.length) * 100))
      }
      setDone(true)
      setTimeout(onSuccess, 1200)
    } catch (err) {
      setParseError(`Upload failed: ${err}`)
      setUploading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg bg-white rounded-2xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className={`h-3 w-3 rounded-full ${cfg.color}`} />
            <div>
              <h2 className="text-sm font-bold text-gray-900">Upload {cfg.label} Report</h2>
              <p className="text-xs text-gray-500">{cfg.desc}</p>
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="h-5 w-5" /></button>
        </div>

        <div className="p-6 space-y-4">
          {/* Tip */}
          <button
            onClick={() => setShowTip(v => !v)}
            className="w-full flex items-center justify-between text-xs text-orange-700 bg-orange-50 border border-orange-200 rounded-lg px-3 py-2"
          >
            <span>Where to download this report?</span>
            {showTip ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>
          {showTip && (
            <div className="text-xs text-orange-700 bg-orange-50 border border-orange-200 rounded-lg px-3 py-2 -mt-2">
              {cfg.tip}
            </div>
          )}

          {/* Drop zone */}
          {!rows.length && !done && (
            <div
              onDragOver={e => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={e => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if (f) parseFile(f) }}
              onClick={() => fileRef.current?.click()}
              className={`flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-10 cursor-pointer transition-colors ${dragging ? 'border-orange-400 bg-orange-50' : 'border-gray-200 hover:border-orange-300 hover:bg-orange-50/40'}`}
            >
              <Upload className="h-8 w-8 text-gray-300" />
              <div className="text-center">
                <p className="text-sm font-medium text-gray-700">Drop your CSV or Excel file here</p>
                <p className="text-xs text-gray-400 mt-1">or click to browse</p>
              </div>
              <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" className="hidden"
                onChange={e => { const f = e.target.files?.[0]; if (f) parseFile(f) }} />
            </div>
          )}

          {/* Parse error */}
          {parseError && (
            <div className="flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 p-3">
              <AlertCircle className="h-4 w-4 text-red-500 shrink-0 mt-0.5" />
              <p className="text-xs text-red-700">{parseError}</p>
            </div>
          )}

          {/* Preview */}
          {rows.length > 0 && !done && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-green-500" />
                  <span className="text-sm font-medium text-gray-800">{fileName}</span>
                </div>
                <span className="text-xs text-gray-500">{rows.length} campaigns detected</span>
              </div>

              {/* Mini preview table */}
              <div className="rounded-lg border border-gray-100 overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-gray-50">
                      <th className="text-left px-3 py-2 text-gray-500 font-medium">Campaign</th>
                      <th className="text-right px-3 py-2 text-gray-500 font-medium">Spend</th>
                      <th className="text-right px-3 py-2 text-gray-500 font-medium">Sales</th>
                      <th className="text-right px-3 py-2 text-gray-500 font-medium">ACoS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.slice(0, 4).map((r, i) => (
                      <tr key={i} className="border-t border-gray-50">
                        <td className="px-3 py-1.5 text-gray-800 truncate max-w-[160px]">{String(r.campaign_name)}</td>
                        <td className="px-3 py-1.5 text-right text-gray-700">₹{Number(r.spend).toLocaleString('en-IN')}</td>
                        <td className="px-3 py-1.5 text-right text-gray-700">₹{Number(r.sales).toLocaleString('en-IN')}</td>
                        <td className="px-3 py-1.5 text-right text-gray-700">{Number(r.acos) > 0 ? `${Number(r.acos).toFixed(1)}%` : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {rows.length > 4 && <p className="text-center text-[10px] text-gray-400 py-1.5">+{rows.length - 4} more rows</p>}
              </div>

              {/* Upload progress */}
              {uploading && (
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs text-gray-500">
                    <span>Uploading…</span><span>{progress}%</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-gray-100">
                    <div className="h-1.5 rounded-full bg-orange-500 transition-all" style={{ width: `${progress}%` }} />
                  </div>
                </div>
              )}

              {!uploading && (
                <button onClick={handleUpload}
                  className="w-full rounded-lg bg-orange-500 py-2.5 text-sm font-bold text-white hover:bg-orange-600 transition-colors">
                  Upload {rows.length} Campaigns
                </button>
              )}
            </div>
          )}

          {/* Done */}
          {done && (
            <div className="flex flex-col items-center gap-3 py-6">
              <CheckCircle className="h-12 w-12 text-green-500" />
              <p className="text-sm font-bold text-gray-900">Upload complete!</p>
              <p className="text-xs text-gray-500">{rows.length} campaigns saved successfully</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
