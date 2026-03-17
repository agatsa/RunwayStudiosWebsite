import { NextRequest, NextResponse } from 'next/server'

export async function POST(req: NextRequest) {
  const base = process.env.FASTAPI_BASE_URL ?? 'http://localhost:8080'
  const token = process.env.CRON_TOKEN ?? ''
  const formData = await req.formData()
  const r = await fetch(`${base}/email/upload-image`, {
    method: 'POST',
    headers: { 'X-Cron-Token': token },
    body: formData,
  })
  const data = await r.json()
  return NextResponse.json(data, { status: r.ok ? 200 : r.status })
}
