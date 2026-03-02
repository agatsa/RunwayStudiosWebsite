import {
  Document, Packer, Paragraph, Table, TableRow, TableCell,
  TextRun, HeadingLevel, AlignmentType, WidthType, BorderStyle,
  ShadingType, TableLayoutType, PageOrientation, Header,
  Footer, PageNumber, NumberFormat
} from 'docx'
import { writeFileSync } from 'fs'

const PURPLE      = '5B21B6'
const PURPLE_LIGHT= 'EDE9FE'
const PURPLE_MID  = '7C3AED'
const GRAY_DARK   = '111827'
const GRAY_MID    = '374151'
const GRAY_LIGHT  = 'F9FAFB'
const WHITE       = 'FFFFFF'
const GREEN_BG    = 'DCFCE7'
const GREEN_FG    = '166534'
const BLUE_BG     = 'DBEAFE'
const BLUE_FG     = '1E40AF'

// ── helpers ──────────────────────────────────────────────────────────────────

const heading = (text, level = 1) => new Paragraph({
  text,
  heading: level === 1 ? HeadingLevel.HEADING_1 : level === 2 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_3,
  spacing: { before: level === 1 ? 360 : 240, after: 120 },
  shading: level === 1 ? { type: ShadingType.SOLID, color: PURPLE_LIGHT, fill: PURPLE_LIGHT } : undefined,
  indent: level === 1 ? { left: 160 } : undefined,
  children: [new TextRun({
    text,
    bold: true,
    color: level === 1 ? PURPLE : level === 2 ? PURPLE_MID : GRAY_DARK,
    size: level === 1 ? 28 : level === 2 ? 24 : 22,
    font: 'Calibri',
  })]
})

const para = (text, { bold = false, color = GRAY_MID, size = 20, spacing = 120, italic = false } = {}) =>
  new Paragraph({
    spacing: { after: spacing },
    children: [new TextRun({ text, bold, color, size, font: 'Calibri', italics: italic })]
  })

const bullet = (text) => new Paragraph({
  bullet: { level: 0 },
  spacing: { after: 80 },
  children: [new TextRun({ text, size: 20, color: GRAY_MID, font: 'Calibri' })]
})

const numberedPara = (text, n) => new Paragraph({
  spacing: { after: 80 },
  children: [
    new TextRun({ text: `${n}.  `, bold: true, color: PURPLE_MID, size: 20, font: 'Calibri' }),
    new TextRun({ text, size: 20, color: GRAY_MID, font: 'Calibri' })
  ]
})

const spacer = (lines = 1) => new Paragraph({ spacing: { after: lines * 160 } })

// ── table helpers ─────────────────────────────────────────────────────────────

const cell = (text, { bold = false, bg = WHITE, color = GRAY_DARK, isHeader = false, width = null, shade = null } = {}) =>
  new TableCell({
    width: width ? { size: width, type: WidthType.PERCENTAGE } : undefined,
    shading: { type: ShadingType.SOLID, color: shade || bg, fill: shade || bg },
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({
      children: [new TextRun({
        text: String(text),
        bold: bold || isHeader,
        color: isHeader ? PURPLE : color,
        size: isHeader ? 18 : 19,
        font: 'Calibri',
      })]
    })]
  })

const headerRow = (...cols) => new TableRow({
  tableHeader: true,
  children: cols.map(c => cell(c, { isHeader: true, bg: PURPLE_LIGHT, shade: PURPLE_LIGHT }))
})

const dataRow = (cols, even = false) => new TableRow({
  children: cols.map(c =>
    typeof c === 'string'
      ? cell(c, { bg: even ? GRAY_LIGHT : WHITE })
      : cell(c.text, { bold: c.bold, bg: even ? GRAY_LIGHT : WHITE, color: c.color || GRAY_DARK })
  )
})

const makeTable = (headers, rows) => new Table({
  layout: TableLayoutType.FIXED,
  width: { size: 100, type: WidthType.PERCENTAGE },
  rows: [
    headerRow(...headers),
    ...rows.map((r, i) => dataRow(r, i % 2 === 1))
  ]
})

// ── infobox ───────────────────────────────────────────────────────────────────

const infoBox = (text) => new Table({
  width: { size: 100, type: WidthType.PERCENTAGE },
  rows: [new TableRow({ children: [
    new TableCell({
      shading: { type: ShadingType.SOLID, color: PURPLE_LIGHT, fill: PURPLE_LIGHT },
      borders: {
        left: { style: BorderStyle.THICK, size: 12, color: PURPLE_MID },
        top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE }
      },
      margins: { top: 120, bottom: 120, left: 180, right: 180 },
      children: [new Paragraph({ children: [new TextRun({ text, size: 19, color: PURPLE, font: 'Calibri', italics: true })] })]
    })
  ]})]
})

// ── COVER ─────────────────────────────────────────────────────────────────────

const coverSection = [
  new Paragraph({
    spacing: { before: 400, after: 160 },
    children: [new TextRun({ text: 'RUNWAY STUDIOS', bold: true, color: PURPLE, size: 36, font: 'Calibri', allCaps: true })]
  }),
  new Paragraph({
    spacing: { after: 120 },
    children: [new TextRun({ text: 'AI Growth OS — Google Ads Integration', bold: true, color: GRAY_DARK, size: 48, font: 'Calibri' })]
  }),
  new Paragraph({
    spacing: { after: 80 },
    children: [new TextRun({ text: 'Technical Design Document', color: GRAY_MID, size: 28, font: 'Calibri', italics: true })]
  }),
  spacer(1),
  new Table({
    width: { size: 60, type: WidthType.PERCENTAGE },
    rows: [
      new TableRow({ children: [
        cell('Version',          { bold: true, bg: PURPLE_LIGHT }),
        cell('1.0',              { bg: WHITE })
      ]}),
      new TableRow({ children: [
        cell('Date',             { bold: true, bg: PURPLE_LIGHT }),
        cell('February 2026',   { bg: GRAY_LIGHT })
      ]}),
      new TableRow({ children: [
        cell('Website',          { bold: true, bg: PURPLE_LIGHT }),
        cell('runwaystudios.co', { bg: WHITE })
      ]}),
      new TableRow({ children: [
        cell('Contact Email',    { bold: true, bg: PURPLE_LIGHT }),
        cell('hello@runwaystudios.co', { bg: GRAY_LIGHT })
      ]}),
      new TableRow({ children: [
        cell('API Access Level', { bold: true, bg: PURPLE_LIGHT }),
        cell('Basic Access (Requested)', { bg: WHITE })
      ]}),
    ]
  }),
  spacer(2),
]

// ── SECTION 1 ─────────────────────────────────────────────────────────────────

const section1 = [
  heading('1. Product Overview'),
  para('Runway Studios AI Growth OS is a SaaS marketing intelligence platform built for Indian D2C brands and digital agencies. It aggregates advertising performance data from multiple platforms — Meta Ads, Google Ads, and YouTube — into a unified analytics dashboard, and applies AI (Claude by Anthropic) to generate cross-channel performance insights and prioritised optimisation recommendations.'),
  para('The platform is hosted on Google Cloud Run (asia-south1) and serves clients through a web dashboard. All Google Ads data is accessed via the Google Ads API exclusively for read-only reporting purposes.'),
  spacer(0.5),
  infoBox('Core Principle: The Google Ads API is used solely for reading performance data. The application does not create, modify, pause, enable, or delete any campaigns, ad groups, ads, keywords, or any other Google Ads entity.'),
  spacer(1),
]

// ── SECTION 2 ─────────────────────────────────────────────────────────────────

const section2 = [
  heading('2. System Architecture'),
  para('The platform consists of four main layers:', { bold: true }),
  bullet('Frontend Dashboard — Next.js 14 web app served from Google Cloud Run'),
  bullet('Backend API — Python FastAPI service handling business logic and API orchestration'),
  bullet('Database — PostgreSQL on Google Cloud SQL for storing KPIs, tokens, and workspace config'),
  bullet('AI Engine — Anthropic Claude API for generating cross-channel recommendations'),
  spacer(0.5),
  makeTable(
    ['Component', 'Technology', 'Role', 'Location'],
    [
      ['Frontend Dashboard', 'Next.js 14, Tailwind CSS', 'Analytics UI for clients', 'Cloud Run (asia-south1)'],
      ['Backend API', 'Python 3.11, FastAPI', 'Business logic, API orchestration', 'Cloud Run (asia-south1)'],
      ['Database', 'PostgreSQL 14 (Cloud SQL)', 'KPI data, OAuth tokens, config', 'Cloud SQL (asia-south1)'],
      ['AI Engine', 'Claude API (Anthropic)', 'Cross-channel analysis, recommendations', 'Anthropic API (external)'],
      ['Google Ads Connector', 'google-ads Python SDK v24', 'Fetches metrics via GAQL', 'Within backend service'],
    ]
  ),
  spacer(1),
]

// ── SECTION 3 ─────────────────────────────────────────────────────────────────

const section3 = [
  heading('3. Authentication & Authorisation'),
  heading('OAuth2 Flow', 2),
  para('The platform uses Google\'s standard OAuth2 authorisation code flow. No user passwords are stored at any point. Access is granted explicitly by the account owner through Google\'s consent screen.'),
  numberedPara('User clicks "Connect Google Ads" in the Settings page', 1),
  numberedPara('Platform redirects to accounts.google.com/oauth2/auth with requested scopes', 2),
  numberedPara('User reviews and consents on Google\'s consent screen', 3),
  numberedPara('Google returns authorisation code to our callback endpoint', 4),
  numberedPara('Backend exchanges code for access_token + refresh_token', 5),
  numberedPara('Tokens stored encrypted in Cloud SQL, scoped to the user\'s workspace_id', 6),
  numberedPara('All subsequent Google Ads API calls use the stored refresh token', 7),
  spacer(0.5),
  heading('OAuth2 Scopes Requested', 2),
  makeTable(
    ['Scope', 'Purpose', 'Access Type'],
    [
      ['https://www.googleapis.com/auth/adwords', 'Read Google Ads performance data via GAQL', 'Read Only'],
      ['https://www.googleapis.com/auth/youtube.readonly', 'Read YouTube channel stats and video metadata', 'Read Only'],
      ['https://www.googleapis.com/auth/yt-analytics.readonly', 'Read YouTube Analytics (watch time, CTR)', 'Read Only'],
    ]
  ),
  spacer(0.5),
  heading('Token Storage & Security', 2),
  bullet('Access tokens and refresh tokens stored in encrypted columns in PostgreSQL (Cloud SQL, asia-south1)'),
  bullet('Tokens are workspace-scoped — each client\'s tokens are isolated by workspace_id'),
  bullet('Refresh tokens are used automatically when access tokens expire (1-hour standard expiry)'),
  bullet('Users can revoke access at any time via Google Account settings or the platform\'s Settings page'),
  bullet('Tokens are never logged, exposed in API responses, or sent to the frontend'),
  spacer(1),
]

// ── SECTION 4 ─────────────────────────────────────────────────────────────────

const section4 = [
  heading('4. Google Ads API Usage'),
  para('All API calls use GAQL (Google Ads Query Language) SELECT queries only. No mutate operations are performed. The following table lists every report type accessed:'),
  spacer(0.5),
  makeTable(
    ['Report Type', 'GAQL Resource', 'Fields Retrieved', 'Dashboard Purpose'],
    [
      ['Campaign Performance', 'campaign', 'name, status, impressions, clicks, cost, conversions, conversion_value, date', 'KPI cards, spend charts, ROAS calculation'],
      ['Keyword Performance', 'keyword_view', 'keyword_text, match_type, quality_score, impressions, clicks, cost, conversions', 'Keyword analysis, QS badges, wasted spend'],
      ['Search Terms', 'search_term_view', 'search_term, campaign, ad_group, clicks, cost, conversions', 'Negative keyword recommendations'],
      ['Geographic Performance', 'geographic_view', 'location_type, location_name, campaign, impressions, clicks, cost, conversions', 'City/region ROAS, expansion opportunities'],
      ['Device Performance', 'campaign (device segment)', 'device, campaign, impressions, clicks, cost, conversions', 'Mobile vs desktop budget split'],
      ['Time of Day', 'campaign (hour/day segment)', 'hour_of_day, day_of_week, cost, conversions', 'Ad scheduling heatmap'],
      ['Auction Insights', 'auction_insight', 'competitor_domain, impression_share, overlap_rate, position_above_rate', 'Competitive position analysis'],
      ['Ad Assets (RSA)', 'ad_group_ad', 'asset_text, asset_type, performance_label, impressions, clicks', 'Creative performance analysis'],
      ['Account Discovery', 'CustomerService.listAccessibleCustomers', 'customer_id, descriptive_name', 'Multi-account agency management'],
    ]
  ),
  spacer(0.5),
  infoBox('No Mutate Operations: The application does not call any Google Ads API write methods. There are no calls to CampaignService.mutate, AdGroupService.mutate, BudgetService.mutate, KeywordService.mutate, or any other operation that modifies Google Ads data.'),
  spacer(1),
]

// ── SECTION 5 ─────────────────────────────────────────────────────────────────

const section5 = [
  heading('5. Data Flow & Storage'),
  heading('Ingestion Pipeline', 2),
  numberedPara('User authenticates via OAuth2 and grants read access to their Google Ads account', 1),
  numberedPara('FastAPI backend calls Google Ads API using the stored refresh token', 2),
  numberedPara('Performance metrics retrieved for the requested date range via GAQL SELECT queries', 3),
  numberedPara('Data normalised and stored in the kpi_hourly table in PostgreSQL, keyed by workspace_id, platform, entity_level, and timestamp', 4),
  numberedPara('Next.js dashboard reads this data via internal REST API endpoints (authenticated)', 5),
  numberedPara('Claude AI analyses aggregated data and returns text recommendations (not persisted)', 6),
  spacer(0.5),
  heading('Data Retention & Isolation', 2),
  makeTable(
    ['Data Type', 'Storage Location', 'Isolation Key', 'Retention Policy'],
    [
      ['OAuth tokens', 'Cloud SQL (encrypted columns)', 'workspace_id', 'Until revoked or account deleted'],
      ['Campaign KPI data', 'Cloud SQL · kpi_hourly table', 'workspace_id', 'Duration of active account'],
      ['Keyword / search term data', 'Cloud SQL · kpi_hourly table', 'workspace_id', 'Duration of active account'],
      ['AI-generated recommendations', 'Not stored — generated on-demand per session', 'N/A', 'Not persisted'],
    ]
  ),
  spacer(1),
]

// ── SECTION 6 ─────────────────────────────────────────────────────────────────

const section6 = [
  heading('6. Multi-Account (Agency) Support'),
  para('The platform supports agencies managing multiple client Google Ads accounts. Each client account maps to a separate Workspace. The implementation follows Google\'s recommended Manager Account (MCC) model:'),
  bullet('A single OAuth2 token from the agency\'s Google account (with MCC access) covers multiple client accounts'),
  bullet('CustomerService.listAccessibleCustomers called once to discover available customer IDs'),
  bullet('Each GAQL query specifies the target login-customer-id header to scope results to the correct client'),
  bullet('Client data strictly isolated by workspace_id — no cross-client data leakage is architecturally possible'),
  spacer(0.5),
  makeTable(
    ['Scenario', 'Implementation'],
    [
      ['Brand managing own account', 'Direct OAuth2 with their Google account. Single customer_id used in all requests.'],
      ['Agency managing client accounts', 'OAuth2 with agency MCC account. Per-client login-customer-id header in each GAQL request.'],
    ]
  ),
  spacer(1),
]

// ── SECTION 7 ─────────────────────────────────────────────────────────────────

const section7 = [
  heading('7. Security & Compliance'),
  makeTable(
    ['Security Control', 'Implementation', 'Status'],
    [
      ['Data encryption at rest', 'Google Cloud SQL with encryption enabled by default', 'Active'],
      ['Data encryption in transit', 'TLS 1.2+ on all API endpoints — Cloud Run managed certificates', 'Active'],
      ['OAuth token security', 'Tokens stored in encrypted DB columns, never exposed in logs or API responses', 'Active'],
      ['API authentication', 'All internal endpoints require Bearer token — no unauthenticated access', 'Active'],
      ['Data residency', 'All data stored in Google Cloud asia-south1 (Mumbai, India)', 'Active'],
      ['No third-party data sharing', 'Google Ads data never shared with, sold to, or transferred to any third party', 'Active'],
      ['Access revocation', 'Users can disconnect Google Ads at any time via Settings page or Google Account', 'Active'],
      ['Minimal scope principle', 'Only read-only scopes requested — no write, manage, or admin scopes', 'Active'],
      ['Workspace isolation', 'All DB queries filter by workspace_id — tenant data fully isolated', 'Active'],
    ]
  ),
  spacer(1),
]

// ── SECTION 8 ─────────────────────────────────────────────────────────────────

const section8 = [
  heading('8. Google Ads API Policy Compliance'),
  makeTable(
    ['Policy Requirement', 'How Runway Studios Complies'],
    [
      ['Accurate application information', 'All information provided reflects the actual production system at runwaystudios.co'],
      ['Data use limitation', 'Google Ads data used exclusively for analytics and AI recommendations within the platform, only for the data owner'],
      ['No resale of data', 'Google Ads performance data is never sold, licensed, or transferred to any third party'],
      ['No scraping or bulk export', 'Data retrieved for dashboard display and AI analysis only — no bulk exports or redistribution'],
      ['User consent required', 'Each user explicitly grants access via Google\'s OAuth2 consent screen before any API call is made'],
      ['Valid privacy policy', 'Published at runwaystudios.co/#privacy — includes specific Google Ads API data handling section'],
      ['API contact email monitored', 'hello@runwaystudios.co — checked daily, response within 24 business hours'],
      ['Read-only access', 'No mutate, create, or delete operations are performed on any Google Ads entity'],
    ]
  ),
  spacer(1),
]

// ── SECTION 9 ─────────────────────────────────────────────────────────────────

const section9 = [
  heading('9. Technology Stack Summary'),
  makeTable(
    ['Layer', 'Technology', 'Version / Details'],
    [
      ['Backend Language', 'Python', '3.11+'],
      ['Backend Framework', 'FastAPI + Uvicorn', 'Latest stable'],
      ['Google Ads SDK', 'google-ads (Python client library)', '24.x'],
      ['Frontend Framework', 'Next.js (React)', '14.2'],
      ['Database', 'PostgreSQL (Google Cloud SQL)', '14'],
      ['Hosting', 'Google Cloud Run', 'asia-south1 (Mumbai)'],
      ['AI / LLM', 'Claude API (Anthropic)', 'claude-sonnet-4-6'],
      ['Authentication', 'Google OAuth2 + Clerk (dashboard users)', 'Standard OAuth2 flow'],
      ['Domain', 'runwaystudios.co', 'Hosted on GitHub Pages + GoDaddy DNS'],
    ]
  ),
  spacer(1),
]

// ── SECTION 10 ────────────────────────────────────────────────────────────────

const section10 = [
  heading('10. Contact & Support'),
  makeTable(
    ['Type', 'Details'],
    [
      ['Company Name', 'Runway Studios'],
      ['Website', 'https://runwaystudios.co'],
      ['API Contact Email', 'hello@runwaystudios.co'],
      ['Support Phone', '+91 88262 83840'],
      ['Dashboard URL', 'https://dashboard-771420308292.asia-south1.run.app'],
      ['Privacy Policy', 'https://runwaystudios.co/#privacy'],
      ['Data Storage Location', 'Google Cloud asia-south1 (Mumbai, India)'],
      ['Developer Token Location', 'Google Ads Manager Account — API Center'],
    ]
  ),
  spacer(1),
]

// ── BUILD DOCUMENT ────────────────────────────────────────────────────────────

const doc = new Document({
  title: 'Runway Studios — Technical Design Document',
  description: 'Google Ads API Integration Design Document',
  creator: 'Runway Studios',
  styles: {
    default: {
      document: {
        run: { font: 'Calibri', size: 20, color: GRAY_MID },
      },
    },
    paragraphStyles: [
      {
        id: 'Normal',
        name: 'Normal',
        run: { font: 'Calibri', size: 20 },
      },
    ],
  },
  sections: [{
    properties: {
      page: {
        margin: { top: 1000, bottom: 1000, left: 1200, right: 1200 },
      },
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: PURPLE_LIGHT } },
          children: [
            new TextRun({ text: 'Runway Studios — Technical Design Document', size: 16, color: PURPLE, font: 'Calibri' }),
            new TextRun({ text: '   |   Confidential   |   v1.0   |   February 2026', size: 16, color: 'AAAAAA', font: 'Calibri' }),
          ]
        })]
      })
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: 'runwaystudios.co   ·   hello@runwaystudios.co   ·   Page ', size: 16, color: 'AAAAAA', font: 'Calibri' }),
            new TextRun({ children: [PageNumber.CURRENT], size: 16, color: 'AAAAAA', font: 'Calibri' }),
          ]
        })]
      })
    },
    children: [
      ...coverSection,
      ...section1,
      ...section2,
      ...section3,
      ...section4,
      ...section5,
      ...section6,
      ...section7,
      ...section8,
      ...section9,
      ...section10,
    ]
  }]
})

const buffer = await Packer.toBuffer(doc)
writeFileSync('Runway-Studios-Design-Document.docx', buffer)
console.log('SUCCESS: Runway-Studios-Design-Document.docx created')
