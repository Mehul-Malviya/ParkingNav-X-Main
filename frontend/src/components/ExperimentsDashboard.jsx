import React, { useState, useEffect } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, RadarChart, Radar, PolarGrid,
  PolarAngleAxis, PolarRadiusAxis
} from 'recharts'
import { api } from '../api'

const STRATEGIES = ['B1', 'B2', 'B3', 'P']
const STRATEGY_COLORS = { B1: '#94a3b8', B2: '#60a5fa', B3: '#a78bfa', P: '#10b981' }
const METRICS = [
  { key: 'avg_search_time_min', label: 'Avg Search Time (min)', lower: true },
  { key: 'avg_wait_time_min',   label: 'Avg Wait Time (min)',   lower: true },
  { key: 'avg_gate_queue',      label: 'Avg Gate Queue',        lower: true },
  { key: 'overflow_events',     label: 'Overflow Events',       lower: true },
]

export default function ExperimentsDashboard() {
  const [results, setResults] = useState({})
const [loading, setLoading] = useState(false)
const [scenarios, setScenarios] = useState([])
const [selectedScenario, setSelectedScenario] = useState('')
const [selectedMetric, setSelectedMetric] = useState('avg_search_time_min')
const [progress, setProgress] = useState([])
const [scenarioError, setScenarioError] = useState('')

useEffect(() => {
  const loadScenarios = async () => {
    try {
      setScenarioError('')

      const res = await api.getScenarios()
      const availableScenarios = res.data.scenarios ?? []

      setScenarios(availableScenarios)

      if (availableScenarios.length > 0) {
        setSelectedScenario(current =>
          availableScenarios.includes(current)
            ? current
            : availableScenarios[0]
        )
      } else {
        setScenarioError('The API returned no scenarios.')
      }
    } catch (error) {
      setScenarioError(
        error.response?.data?.detail ||
        error.message ||
        'Failed to load scenarios.'
      )
    }
  }

  loadScenarios()
}, [])

  const runExperiments = async () => {
  if (scenarios.length === 0) {
    setProgress(['No scenarios are available to run.'])
    return
  }

  setLoading(true)
  setProgress([])
  setResults({})

  const newResults = {}

  try {
    for (const scenario of scenarios) {
      try {
        const res = await api.compareStrategies(scenario)
        const comparison = res.data?.comparison

        if (!comparison) {
          throw new Error('No comparison data returned')
        }

        newResults[scenario] = comparison
        setResults({ ...newResults })
        setProgress(p => [...p, `✓ ${scenario}`])
      } catch (error) {
        setProgress(p => [
          ...p,
          `✗ ${scenario}: ${
            error.response?.data?.detail ||
            error.message ||
            'Request failed'
          }`,
        ])
      }
    }
  } finally {
    setLoading(false)
  }
}

  // Build chart data for selected scenario
  const scenarioData = results[selectedScenario] || {}
  const chartData = METRICS.map(m => ({
    metric: m.label,
    B1: scenarioData.B1?.[m.key] ?? null,
    B2: scenarioData.B2?.[m.key] ?? null,
    B3: scenarioData.B3?.[m.key] ?? null,
    P: scenarioData.P?.[m.key] ?? null,
  }))

  // Radar data (normalized) for selected scenario
  const metricMaxes = METRICS.map(m => {
  const values = STRATEGIES
    .map(s => scenarioData[s]?.[m.key])
    .filter(v => typeof v === 'number' && Number.isFinite(v))

  return values.length > 0
    ? Math.max(...values, 1)
    : null
})
  const radarData = STRATEGIES.map(strategy => {
  const point = { strategy }

  METRICS.forEach((m, i) => {
    const val = scenarioData[strategy]?.[m.key]
    const max = metricMaxes[i]

    if (
      typeof val !== 'number' ||
      !Number.isFinite(val) ||
      max === null
    ) {
      point[m.label] = null
    } else {
      // Lower values are better for these metrics.
      point[m.label] = m.lower ? 1 - val / max : val / max
    }
  })

  return point
})

  // Summary table: all scenarios × all strategies
  const hasResults = Object.keys(results).length > 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-gray-800">Experiments Dashboard</h2>
          <p className="text-sm text-gray-500">
            Compare available scenarios across the supported strategies.
          </p>
        </div>
        <button
          onClick={runExperiments}
          disabled={loading}
          className="px-4 py-2 bg-vitap-blue text-white rounded-md text-sm font-medium hover:bg-blue-800 disabled:opacity-50"
        >
          {loading ? '⏳ Running Experiments...' : '🔬 Run All Experiments'}
        </button>
      </div>

      {/* Progress log */}
      {progress.length > 0 && (
        <div className="bg-gray-900 text-green-400 rounded-lg p-3 text-xs font-mono space-y-0.5 max-h-32 overflow-y-auto">
          {progress.map((line, i) => <div key={i}>{line}</div>)}
          {loading && <div className="animate-pulse">Running...</div>}
        </div>
      )}

      {/* Controls */}
      {hasResults && (
        <div className="bg-white rounded-lg shadow p-4">
          <div className="flex gap-4 items-center flex-wrap">
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">Scenario</label>
              <select
                value={selectedScenario}
                onChange={e => setSelectedScenario(e.target.value)}
                className="border border-gray-300 rounded px-2 py-1 text-sm"
              >
                {scenarioError && (
                  <p className="text-sm text-red-600" role="alert">
                    {scenarioError}
                  </p>
                )}
                {scenarios
                  .filter(s => results[s])
                  .map(s => (
                    <option key={s} value={s}>
                      {s.replace(/_/g, ' ')}
                    </option>
                  ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">Primary Metric</label>
              <select
                value={selectedMetric}
                onChange={e => setSelectedMetric(e.target.value)}
                className="border border-gray-300 rounded px-2 py-1 text-sm"
              >
                {METRICS.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
              </select>
            </div>
          </div>
        </div>
      )}

      {hasResults && (
        <>
          {/* Strategy Comparison Bar Chart */}
          <div className="bg-white rounded-lg shadow p-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">
              Strategy Comparison — {selectedScenario.replace(/_/g, ' ')}
            </h3>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={chartData} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="metric" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                {STRATEGIES.map(s => (
                  <Bar key={s} dataKey={s} fill={STRATEGY_COLORS[s]} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Summary Table (all scenarios) */}
          <div className="bg-white rounded-lg shadow p-4 overflow-x-auto">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">Results Summary Table</h3>
            <table className="min-w-full text-xs">
              <thead>
                <tr className="border-b bg-gray-50">
                  <th className="text-left py-2 px-3 text-gray-500">Scenario</th>
                  <th className="text-left py-2 px-3 text-gray-500">Strategy</th>
                  <th className="text-right py-2 px-3 text-gray-500">Search (min)</th>
                  <th className="text-right py-2 px-3 text-gray-500">Wait (min)</th>
                  <th className="text-right py-2 px-3 text-gray-500">Avg Queue</th>
                  <th className="text-right py-2 px-3 text-gray-500">Overflow</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(results).flatMap(([scenario, stratMap]) =>
                  STRATEGIES.map((s, si) => {
                    const m = stratMap[s] || {}
                    const isParkingNav = s === 'P'
                    return (
                      <tr key={`${scenario}-${s}`} className={`border-b ${isParkingNav ? 'bg-green-50 font-semibold' : ''} ${si === 0 ? 'border-t-2 border-gray-300' : ''}`}>
                        <td className="py-1.5 px-3 text-gray-600">{si === 0 ? scenario.replace(/_/g, ' ') : ''}</td>
                        <td className="py-1.5 px-3">
                          <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${isParkingNav ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-700'}`}>{s}</span>
                        </td>
                        <td className="text-right py-1.5 px-3">{m.avg_search_time_min ?? '—'}</td>
                        <td className="text-right py-1.5 px-3">{m.avg_wait_time_min ?? '—'}</td>
                        <td className="text-right py-1.5 px-3">{m.avg_gate_queue ?? '—'}</td>
                        <td className="text-right py-1.5 px-3">{m.overflow_events ?? '—'}</td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!hasResults && !loading && (
        <div className="text-center py-20 bg-white rounded-lg shadow">
          <div className="text-4xl mb-3">🔬</div>

          <div className="text-gray-600">
            {scenarios.length > 0
              ? 'Run the experiments to view actual strategy comparisons.'
              : 'Waiting for available scenarios from the API.'}
          </div>

          <div className="text-xs text-gray-400 mt-2">
            Missing experiment results are not treated as zero.
          </div>
        </div>
      )}
    </div>
  )
}
