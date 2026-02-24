// ── Workspace ──────────────────────────────────────────────

export interface Workspace {
  id: string
  name: string
  store_url?: string
  store_platform?: string
  active: boolean
}

// ── KPI / Dashboard ────────────────────────────────────────

export interface PlatformTotals {
  spend: number
  impressions: number
  clicks: number
  conversions: number
  revenue: number
  roas: number
  ctr: number
}

export interface KpiSummary extends PlatformTotals {
  platform_breakdown: {
    meta?: PlatformTotals
    google?: PlatformTotals
  }
}

export interface DailyKpiRow {
  date: string        // ISO "YYYY-MM-DD"
  platform: string   // "meta" | "google"
  spend: number
  impressions: number
  clicks: number
  conversions: number
  revenue: number
  roas: number
  ctr: number
}

export interface KpiSummaryResponse {
  summary: KpiSummary
  daily: DailyKpiRow[]
  workspace_id: string
  days: number
}

// ── Action Log / Approvals ─────────────────────────────────

export type ActionStatus = 'pending' | 'approved' | 'rejected' | 'executed' | 'failed'

export interface ActionRow {
  id: string
  platform: string
  entity_level: string
  entity_id: string
  action_type: string
  old_value: string | null
  new_value: string | null
  triggered_by: string
  status: ActionStatus
  ts: string
  executed_at: string | null
  error: string | null
}

export interface ActionsListResponse {
  actions: ActionRow[]
  count: number
  workspace_id: string
}

// ── Campaigns ──────────────────────────────────────────────

export type CampaignStatus = 'ACTIVE' | 'PAUSED' | 'ARCHIVED' | 'DELETED'

export interface MetaCampaign {
  id: string
  name: string
  status: CampaignStatus
  effective_status: string
  objective: string
  daily_budget?: string    // raw paise from Meta
  daily_budget_inr?: number
}

export interface GoogleCampaign {
  id: string
  name: string
  status: string
  budget_amount_micros?: number
  daily_budget_inr?: number
  channel_type?: string
}

export interface MetaCampaignsResponse {
  campaigns: MetaCampaign[]
  workspace_id: string
  error?: string
}

export interface GoogleCampaignsResponse {
  campaigns: GoogleCampaign[]
  error?: string
}

// ── Catalog / Products ─────────────────────────────────────

export type McStatus = 'approved' | 'disapproved' | 'pending' | 'not_synced' | null

export interface Product {
  id: string
  workspace_id: string
  name: string
  description?: string
  price_inr?: number
  mrp_inr?: number
  sku?: string
  images?: string[]           // JSONB array of URLs
  product_url?: string
  category?: string
  brand?: string
  source_platform?: string
  active: boolean
  mc_status?: McStatus
  mc_disapproval_reasons?: string[]
  mc_last_sync?: string
  last_synced_at?: string
  created_at?: string
  updated_at?: string
}

export interface ProductsResponse {
  products: Product[]
  count: number
}

export interface DisapprovalItem {
  product_id: string
  name: string
  reasons: string[]
  mc_offer_id: string
}

export interface DisapprovalsResponse {
  disapproved: DisapprovalItem[]
  count: number
}

// -- Platform Connections / Settings ----------------------------------------

export interface PlatformConnection {
  platform: string
  account_id: string
  account_name: string | null
  ad_account_id: string | null
  is_primary: boolean
  connected_at: string | null
  has_token: boolean
}

// ── YouTube ─────────────────────────────────────────────────

export interface YouTubeChannelInfo {
  channel_id: string
  title: string
  description: string
  thumbnail: string | null
  subscriber_count: number
  view_count: number
  video_count: number
}

export interface YouTubeChannelStatRow {
  date: string               // YYYY-MM-DD
  views: number
  watch_time_minutes: number
  subscribers_gained: number
  subscribers_lost: number
  impressions: number
  impression_ctr: number     // percentage e.g. 4.5
}

export interface YouTubeChannelStatsResponse {
  channel: YouTubeChannelInfo
  daily: YouTubeChannelStatRow[]
  analytics_available?: boolean
  since: string
  until: string
  workspace_id: string
}

export interface YouTubeVideo {
  video_id: string
  title: string
  description: string
  tags: string[]
  thumbnail_url: string | null
  published_at: string | null
  duration_seconds: number
  view_count: number
  like_count: number
  comment_count: number
}

export interface YouTubeVideosResponse {
  videos: YouTubeVideo[]
  count: number
  workspace_id: string
}

export interface YouTubeVideoStatRow {
  date: string
  views: number
  watch_time_minutes: number
  avg_view_duration_seconds: number
  avg_view_percentage: number
  impressions: number
  impression_ctr: number
  likes: number
  shares: number
  subscribers_gained: number
}

export interface YouTubeVideoInsightsResponse {
  video_id: string
  total_views: number
  total_watch_minutes: number
  avg_view_percentage: number
  avg_ctr: number
  avg_duration_seconds: number
  subscribers_gained: number
  daily: YouTubeVideoStatRow[]
  suggestions: string[]
  workspace_id: string
}

export interface YouTubeGrowthPlanResponse {
  channel: YouTubeChannelInfo
  steps: string[]
  workspace_id: string
}

export interface ConnectionsResponse {
  connections: PlatformConnection[]
  workspace_id: string
}
