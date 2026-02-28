'use client'

import { useEffect, useState } from 'react'

const MESSAGES = [
  'Cooking up your dashboard…',
  'AI agents hard at work…',
  'Pulling live performance data…',
  'Crunching the numbers…',
  'Brewing growth insights…',
  'Connecting the dots…',
  'Analysing what\'s working…',
  'Fetching real-time signals…',
]

interface Props {
  /** Short label shown in the bottom sub-line, e.g. "CAMPAIGNS" */
  section?: string
}

export default function PageLoader({ section }: Props) {
  const [msgIdx, setMsgIdx] = useState(() => Math.floor(Math.random() * MESSAGES.length))
  const [visible, setVisible] = useState(true)

  useEffect(() => {
    const id = setInterval(() => {
      setVisible(false)
      setTimeout(() => {
        setMsgIdx(i => (i + 1) % MESSAGES.length)
        setVisible(true)
      }, 280)
    }, 2600)
    return () => clearInterval(id)
  }, [])

  return (
    <>
      <style>{`
        @keyframes rw-cw   { to { transform: rotate(360deg); } }
        @keyframes rw-ccw  { to { transform: rotate(-360deg); } }
        @keyframes rw-glow {
          0%, 100% { opacity: 1; transform: scale(1); filter: drop-shadow(0 0 6px #818cf8); }
          50%       { opacity: .7; transform: scale(.88); filter: drop-shadow(0 0 2px #818cf8); }
        }
        @keyframes rw-bar {
          0%, 100% { transform: scaleY(.25); }
          50%       { transform: scaleY(1); }
        }
        @keyframes rw-shimmer {
          0%   { background-position: -600px 0; }
          100% { background-position:  600px 0; }
        }
        .rw-bone {
          background: linear-gradient(90deg, #f1f5f9 25%, #e8eef5 50%, #f1f5f9 75%);
          background-size: 1200px 100%;
          animation: rw-shimmer 1.8s infinite linear;
          border-radius: .75rem;
        }
      `}</style>

      <div className="flex flex-col items-center pt-16 pb-8 min-h-[60vh] select-none">

        {/* ── Orbital rings ─────────────────────────────────── */}
        <div className="relative w-28 h-28 mb-7">

          {/* Outer ring — slow CW */}
          <svg
            className="absolute inset-0 w-full h-full"
            style={{ animation: 'rw-cw 4s linear infinite' }}
            viewBox="0 0 112 112"
          >
            <defs>
              <linearGradient id="rw-g1" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%"   stopColor="#6366f1" />
                <stop offset="100%" stopColor="#8b5cf6" />
              </linearGradient>
            </defs>
            <circle cx="56" cy="56" r="52"
              fill="none" stroke="url(#rw-g1)" strokeWidth="2.5"
              strokeDasharray="90 240" strokeLinecap="round" />
          </svg>

          {/* Middle ring — medium CCW */}
          <svg
            className="absolute inset-0 w-full h-full"
            style={{ animation: 'rw-ccw 2.8s linear infinite', padding: '12px' }}
            viewBox="0 0 112 112"
          >
            <defs>
              <linearGradient id="rw-g2" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%"   stopColor="#a855f7" />
                <stop offset="100%" stopColor="#ec4899" />
              </linearGradient>
            </defs>
            <circle cx="56" cy="56" r="52"
              fill="none" stroke="url(#rw-g2)" strokeWidth="3"
              strokeDasharray="55 200" strokeLinecap="round" />
          </svg>

          {/* Inner ring — fast CW */}
          <svg
            className="absolute inset-0 w-full h-full"
            style={{ animation: 'rw-cw 1.8s linear infinite', padding: '24px' }}
            viewBox="0 0 112 112"
          >
            <circle cx="56" cy="56" r="52"
              fill="none" stroke="#c7d2fe" strokeWidth="2.5"
              strokeDasharray="32 180" strokeLinecap="round" />
          </svg>

          {/* Centre badge */}
          <div
            className="absolute inset-0 flex items-center justify-center"
            style={{ animation: 'rw-glow 2.2s ease-in-out infinite' }}
          >
            <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 flex items-center justify-center shadow-xl shadow-indigo-200">
              {/* Spark / bolt icon */}
              <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
                <path
                  d="M12.5 2L5 13h6.5L9.5 20 17 9h-6.5L12.5 2Z"
                  fill="white"
                  fillOpacity=".95"
                />
              </svg>
            </div>
          </div>
        </div>

        {/* ── Fading message ────────────────────────────────── */}
        <div className="h-8 flex items-center justify-center mb-4">
          <p
            className="text-[15px] font-semibold text-gray-700 tracking-tight text-center"
            style={{
              opacity: visible ? 1 : 0,
              transition: 'opacity 280ms ease',
            }}
          >
            {MESSAGES[msgIdx]}
          </p>
        </div>

        {/* ── Equalizer bars + label ────────────────────────── */}
        <div className="flex items-center gap-3 mb-10">
          <div className="flex items-end gap-[3px]" style={{ height: '18px' }}>
            {[.35, .65, 1, .55, .9, .45, .75, .5].map((h, i) => (
              <div
                key={i}
                className="w-[3px] rounded-full bg-indigo-400"
                style={{
                  height: `${h * 18}px`,
                  animation: 'rw-bar 1.1s ease-in-out infinite',
                  animationDelay: `${i * 0.11}s`,
                  transformOrigin: 'bottom',
                }}
              />
            ))}
          </div>
          <span className="text-[11px] font-semibold tracking-widest text-gray-400 uppercase">
            Runway AI{section ? ` · ${section}` : ''}
          </span>
        </div>

        {/* ── Shimmer skeleton ──────────────────────────────── */}
        <div className="w-full max-w-3xl space-y-3.5 opacity-60">
          {/* 4 KPI cards */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[100, 80, 92, 70].map((w, i) => (
              <div key={i} className="rw-bone h-[76px]" style={{ width: `${w}%` }} />
            ))}
          </div>
          {/* 2 charts */}
          <div className="grid grid-cols-2 gap-3">
            <div className="rw-bone h-44" />
            <div className="rw-bone h-44" />
          </div>
          {/* Table */}
          <div className="rw-bone h-28" />
        </div>
      </div>
    </>
  )
}
