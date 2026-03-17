import { TrendingUp } from 'lucide-react'
import ComingSoonPage from '@/components/ui/ComingSoonPage'

interface PageProps { searchParams: { ws?: string } }

export default function SearchTrendsPage({ searchParams }: PageProps) {
  return (
    <ComingSoonPage
      icon={TrendingUp}
      title="Search Trends"
      subtitle="Keyword growth signals from your ad and organic data"
      description="See which search terms are rising, which are wasting budget, and where organic search is bringing in buyers — all in one place."
      blockedBy="Google Ads live sync + GA4 connection"
      blockedByDetail="Search term performance data comes from Google Ads keyword reports. Organic trend data requires GA4. Both are coming soon."
      features={[
        { label: 'Breakout keyword detection', description: 'Terms with rapid growth in clicks or impressions' },
        { label: 'Wasted spend keywords', description: 'High spend, zero conversions — pause candidates' },
        { label: 'Organic vs paid keyword overlap', description: 'Avoid bidding on keywords you already rank for' },
        { label: 'Rising search terms from Google Ads', description: 'New queries your ads are matching to' },
        { label: 'GA4 organic traffic sources', description: 'Which search queries drive organic sessions and conversions' },
      ]}
      etaLabel="Coming Soon"
      workspaceId={searchParams.ws}
      ctaLabel="Check API Status"
      ctaHref="/settings"
    />
  )
}
