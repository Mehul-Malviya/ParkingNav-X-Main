import React, { useEffect, useState } from 'react'
import { api } from '../api'

const PRIORITY_STYLES = {
  CRITICAL: 'bg-red-50 border-red-300 text-red-900',
  HIGH:     'bg-orange-50 border-orange-300 text-orange-900',
  INFO:     'bg-blue-50 border-blue-200 text-blue-900',
}

const PRIORITY_ICONS = {
  CRITICAL: '🚨',
  HIGH:     '⚠️',
  INFO:     'ℹ️',
}

// Fallback only: the real profile definitions (with weights) come from GET /optimize/profiles.
const FALLBACK_PROFILES = [
  { id: 'P1', label: 'P1 — Minimize Wait Time', description: '' },
  { id: 'P2', label: 'P2 — Balanced',           description: '' },
  { id: 'P3', label: 'P3 — Minimize Overflow',  description: '' },
]
const WEIGHT_KEYS = [['w1', 'wait'], ['w2', 'queue'], ['w3', 'search'], ['w4', 'balance'], ['w5', 'overflow']]

// One objective term. Bar = this term's share of J (weight x cost / J), so it changes with the
// selected profile; the raw cost does not depend on the profile, the weight does.
function CostBar({ label, weight, cost, contribution, total }) {
  const share = total > 0 ? Math.min(1, contribution / total) : 0
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-32 text-gray-600 shrink-0">{label}</span>
      <div className="flex-1 bg-gray-200 rounded-full h-2">
        <div className="h-2 rounded-full bg-blue-500 transition-all" style={{ width: `${share * 100}%` }} />
      </div>
      <span className="w-40 text-right text-gray-700 tabular-nums">
        {weight.toFixed(2)} × {cost.toFixed(3)} = {contribution.toFixed(3)}
      </span>
    </div>
  )
}

export default function RecommendationPanel() {
  const [recs, setRecs] = useState([])
  const [profile, setProfile] = useState('P1')
  const [profiles, setProfiles] = useState(FALLBACK_PROFILES)
  const [loading, setLoading] = useState(false)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [error, setError] = useState('')

  const fetchRecs = async (wp = profile) => {
    setLoading(true)
    setError('')
    setRecs([])

    try {
      const res = await api.optimize('E1_normal_day', wp)

      if (res.data?.error) {
        throw new Error(res.data.error)
      }

      if (!Array.isArray(res.data?.recommendations)) {
        throw new Error(
          'The optimization API returned an unexpected response.'
        )
      }

      setRecs(res.data.recommendations)
      setLastUpdated(new Date().toLocaleTimeString())
    } catch (e) {
      setError(
        e.response?.data?.detail ||
        e.response?.data?.error ||
        e.message ||
        'Failed to load recommendations.'
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    api.getOptimizeProfiles()
      .then(res => { if (res.data?.profiles?.length) setProfiles(res.data.profiles) })
      .catch(() => {})  // keep the fallback labels; recommendations still load
    fetchRecs()
  }, [])

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-gray-800">Recommendations</h2>
          <p className="text-sm text-gray-500">Proactive parking recommendations from the multi-objective optimizer</p>
        </div>
        {lastUpdated && <span className="text-xs text-gray-400">Updated: {lastUpdated}</span>}
      </div>

      {/* Weight Profile Selector */}
      <div className="bg-white rounded-lg shadow p-4">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Optimization Weight Profile
        </label>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {profiles.map(wp => (
            <label
              key={wp.id}
              className={`flex items-start gap-2 p-3 border rounded-lg cursor-pointer transition-colors ${
                profile === wp.id ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <input
                type="radio"
                name="profile"
                value={wp.id}
                checked={profile === wp.id}
                onChange={e => {
                  setProfile(e.target.value)
                  fetchRecs(e.target.value)
                }}
                className="mt-0.5"
              />
              <div>
                <div className="text-sm font-medium text-gray-800">{wp.label}</div>
                <div className="text-xs text-gray-500">{wp.description}</div>
                {wp.weights && (
                  <div className="mt-1 text-xs text-gray-600 tabular-nums">
                    {WEIGHT_KEYS.map(([k, name]) => `${name} ${wp.weights[k].toFixed(2)}`).join(' · ')}
                  </div>
                )}
              </div>
            </label>
          ))}
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="p-4 bg-red-50 border border-red-200 rounded text-red-700 text-sm"
        >
          Failed to generate recommendations: {error}
          <button
            type="button"
            onClick={() => fetchRecs()}
            className="ml-3 underline font-semibold"
          >
            Retry
          </button>
        </div>
      )}

      {/* Recommendation Cards */}
      {loading ? (
        <div className="text-center py-12 text-gray-400">Generating recommendations...</div>
      ) : (
        <div className="space-y-3">
          {recs.map((rec) => (
            <div key={rec.id} className={`border rounded-lg p-4 ${PRIORITY_STYLES[rec.priority] || 'bg-gray-50 border-gray-200'}`}>
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-lg">{PRIORITY_ICONS[rec.priority] || '📋'}</span>
                  <div>
                    <span className="text-xs font-bold uppercase tracking-wide">{rec.priority}</span>
                    <span className="mx-1 text-xs text-gray-400">·</span>
                    <span className="text-xs text-gray-500">{rec.type?.replace(/_/g, ' ')}</span>
                  </div>
                </div>
                <span className="text-xs text-gray-400">#{rec.id}</span>
              </div>

              <p className="text-sm font-medium mb-2">{rec.message}</p>

              {/* Proactive alert details */}
              {rec.type === 'PROACTIVE_REROUTE' && (
                <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                  <div className="bg-white bg-opacity-60 rounded p-2">
                    <div className="text-gray-500">Current fill</div>
                    <div className="font-bold">{rec.current_fill ? `${(rec.current_fill * 100).toFixed(0)}%` : '—'}</div>
                  </div>
                  <div className="bg-white bg-opacity-60 rounded p-2">
                    <div className="text-gray-500">15-min forecast</div>
                    <div className="font-bold text-red-600">{rec.forecast_fill_15min ? `${(rec.forecast_fill_15min * 100).toFixed(0)}%` : '—'}</div>
                  </div>
                </div>
              )}

              {/* Alternative lots */}
              {rec.type !== 'LOT_RANKING' && rec.alternatives && rec.alternatives.length > 0 && (
                <div className="mt-2">
                  <div className="text-xs text-gray-500 mb-1">Suggested alternatives:</div>
                  <div className="flex gap-2">
                    {rec.alternatives.map(alt => (
                      <div key={alt.lot_id} className="bg-white bg-opacity-70 rounded px-2 py-1 text-xs">
                        <span className="font-medium">{alt.lot_name}</span>
                        <span className="text-gray-500 ml-1">
                          {(() => {
                            const f = alt.forecast_fill ?? alt.forecast_fill_rate_15min
                            return Number.isFinite(f) ? `(${(f * 100).toFixed(0)}% full)` : ''
                          })()}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Lot ranking */}
              {rec.type === 'LOT_RANKING' && rec.ranked_lots && (
                <div className="mt-2 space-y-1.5">
                  <div className="text-xs text-gray-500">
                    J = objective if the next vehicles are sent to that lot, under profile {rec.weight_profile || profile} (lower is better); the bracket is the change from the system J below.
                    {rec.ranked_lots.some(l => l.current_fill_source && l.current_fill_source !== 'recorded') && (
                      <span className="italic"> No recent recorded occupancy for some lots (a snapshot older than 30 min is not treated as current), so the 15-min forecast is used as their current fill.</span>
                    )}
                  </div>
                  {rec.ranked_lots.map((lot, i) => (
                    <div key={lot.lot_id} className={`flex items-center gap-2 text-xs p-2 rounded ${
                      lot.recommended ? 'bg-green-50' : 'bg-white bg-opacity-50'
                    }`}>
                      <span className="text-gray-400 font-bold w-4">#{i + 1}</span>
                      <span className="flex-1 font-medium">{lot.lot_name}</span>
                      <span className="text-gray-500">{lot.available_spaces} spaces free</span>
                      {Number.isFinite(lot.objective_score) && (
                        <span className="text-gray-400" title={`Objective J if the next vehicles go here (profile ${rec.weight_profile || profile})`}>
                          J {lot.objective_score.toFixed(3)}
                          {Number.isFinite(lot.objective_delta) && ` (${lot.objective_delta >= 0 ? '+' : ''}${lot.objective_delta.toFixed(3)})`}
                        </span>
                      )}
                      <span className="text-gray-500 tabular-nums" title={`Current fill source: ${lot.current_fill_source}`}>
                        now {(lot.current_fill_rate * 100).toFixed(0)}%
                      </span>
                      <span className={`font-bold tabular-nums ${lot.forecast_fill_rate_15min >= 0.9 ? 'text-red-600' : lot.forecast_fill_rate_15min >= 0.7 ? 'text-orange-500' : 'text-green-600'}`}>
                        → {(lot.forecast_fill_rate_15min * 100).toFixed(0)}% in 15 min
                      </span>
                      {i === 0
                        ? <span className="text-green-700 font-bold">★ Best</span>
                        : <span className={lot.recommended ? 'text-gray-400' : 'text-red-500 font-semibold'}>
                            {lot.recommended ? 'available' : 'avoid'}
                          </span>}
                    </div>
                  ))}
                </div>
              )}

              {/* Cost function: weights come from the selected profile */}
              {rec.cost_function && (
                <div className="mt-3 p-3 bg-white bg-opacity-60 rounded">
                  <div className="text-xs font-semibold text-gray-600 mb-2">
                    System objective J = {rec.cost_function.J?.toFixed(3) ?? '—'} for the state used to rank
                    ({rec.cost_function.basis || 'current state'}; profile {rec.weight_profile || profile}); each row is weight × cost = contribution.
                  </div>
                  <div className="space-y-1">
                    {[
                      ['Waiting time',    'w1', 'waiting_time'],
                      ['Queue cost',      'w2', 'queue_cost'],
                      ['Search travel',   'w3', 'search_travel'],
                      ['Util. imbalance', 'w4', 'utilization_imbalance'],
                      ['Overflow penalty','w5', 'overflow_penalty'],
                    ].map(([label, wk, ck]) => (
                      <CostBar
                        key={ck}
                        label={label}
                        weight={rec.cost_function.weights?.[wk] ?? 0}
                        cost={rec.cost_function[ck] ?? 0}
                        contribution={rec.cost_function.weighted?.[ck] ?? 0}
                        total={rec.cost_function.J ?? 0}
                      />
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}

          {recs.length === 0 && !loading && (
            <div className="text-center py-12 text-gray-400">
              No recommendations were returned for this scenario and weight profile.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
