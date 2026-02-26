import { Mail, TrendingUp, Users, Repeat, Zap } from 'lucide-react'

interface PageProps { searchParams: { ws?: string } }

export default function EmailIntelPage({ searchParams }: PageProps) {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600">
            <Mail className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Email Intelligence</h1>
            <p className="text-sm text-gray-500">Email sequence performance, revenue attribution, and retention optimization</p>
          </div>
        </div>
        <span className="rounded-full bg-indigo-100 px-3 py-1 text-xs font-semibold text-indigo-700">
          Coming Soon
        </span>
      </div>

      {/* Coming soon card */}
      <div className="rounded-xl border-2 border-dashed border-indigo-200 bg-indigo-50/40 p-12 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-indigo-600 mx-auto">
          <Mail className="h-7 w-7 text-white" />
        </div>
        <h2 className="mt-4 text-base font-semibold text-gray-900">Email Intelligence â Coming Soon</h2>
        <p className="mt-2 text-sm text-gray-500 max-w-md mx-auto">
          Connect Klaviyo or Mailchimp to see which email sequences drive repeat purchases, which subject lines convert, and how email interacts with your paid ad attribution.
        </p>
      </div>

      {/* Planned capabilities */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-100">
              <TrendingUp className="h-4 w-4 text-indigo-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">Revenue per Email</h3>
          </div>
          <p className="text-xs text-gray-500">Track exactly how much revenue each email sequence generates. Identify your highest-value automations and optimize send times, subject lines, and CTAs.</p>
          <div className="mt-3 space-y-2 opacity-30">
            {[
              ['Welcome series', 'â¹8,400 / send'],
              ['Day 3 how-to', 'â¹12,100 / send'],
              ['Cart abandon', 'â¹6,200 / send'],
              ['7-day follow-up', 'â¹3,900 / send']
            ].map(([name, val]) => (
              <div key={name} className="flex justify-between text-xs text-gray-700 rounded-lg bg-gray-50 px-3 py-1.5">
                <span>{name}</span><span className="font-semibold text-green-700">{val}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-green-100">
              <Repeat className="h-4 w-4 text-green-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">Repeat Purchase Attribution</h3>
          </div>
          <p className="text-xs text-gray-500">Which email in your sequence triggers the second purchase? "âDay 3 how-to-use email â 2.3x repeat purchase rate."â Optimize your post-purchase sequence to maximize LTV.</p>
        </div>
        <div className="rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-orange-100">
              <Users className="h-4 w-4 text-orange-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">Segment Performance</h3>
          </div>
          <p className="text-xs text-gray-500">Open rate, click rate, and revenue per recipient broken down by segment. Identify your highest-value audience segments and replicate them in paid ads for lookalike targeting.</p>
        </div>
        <div className="rounded-xl border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-100">
              <Zap className="h-4 w-4 text-purple-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">Ad â Email Attribution</h3>
          </div>
          <p className="text-xs text-gray-500">See the full journey: Meta Ad â Email capture â Welcome sequence â Purchase. True multi-touch attribution showing what email contributes to ROAS that last-click misses.</p>
        </div>
      </div>

      {/* Platform connect cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {[
          { platform: 'Klaviyo', desc: 'Deep e-commerce email analytics with revenue attribution and flow performance breakdown.', color: 'green' },
          { platform: 'Mailchimp', desc: 'Campaign and automation performance with audience segmentation and revenue tracking.', color: 'yellow' },
        ].map(({ platform, desc, color }) => (
          <div key={platform} className={`rounded-xl border border-${color}-200 bg-${color}-50/30 p-5 text-center`}>
            <Mail className={`h-8 w-8 text-${color}-600 mx-auto mb-2`} />
            <p className="text-sm font-semibold text-gray-900">{platform}</p>
            <p className="text-xs text-gray-500 mt-1">{desc}</p>
            <p className={`mt-3 text-xs font-medium text-${color}-600`}>Coming Soon</p>
          </div>
        ))}
      </div>
    </div>
  )
}
