import React, { useEffect, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer
} from 'recharts'
import { api } from '../api'

const STRATEGY_LABELS = {
  B1: 'B1 First Available',
  B2: 'B2 Nearest Available',
  B3: 'B3 Prediction Only',
  P: 'ParkingNav-X',
}

const STRATEGY_COLORS = {
  B1: '#94a3b8',
  B2: '#60a5fa',
  B3: '#a78bfa',
  P: '#10b981',
}

export default function ScenarioControls() {
  const [scenarios, setScenarios] = useState([])
  const [strategies, setStrategies] = useState([])
  const [selectedScenario, setSelectedScenario] = useState('')
  const [selectedStrategy, setSelectedStrategy] = useState('P')
  const [simResult, setSimResult] = useState(null)
  const [compareResult, setCompareResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [comparing, setComparing] = useState(false)

  useEffect(() => {
    Promise.all([api.getScenarios(), api.getStrategies()]).then(([sRes, stRes]) => {
      const scens = sRes.data.scenarios || []
      setScenarios(scens)
      if (scens.length > 0) setSelectedScenario(scens[0])
      setStrategies(stRes.data.strategies || [])
    }).catch(console.error)
  }, [])

  const runSimulation = async () => {
    setLoading(true)
    setSimResult(null)
    try {
      const res = await api.simulate(selectedScenario, selectedStrategy)
      setSimResult(res.data)
    } catch (e) {
      alert(`Simulation failed: ${e.response?.data?.detail || e.message}`)
    } finally {
      setLoading(false)
    }
  }

  const runComparison = async () => {
    setComparing(true)
    setCompareResult(null)
    try {
      const res = await api.compareStrategies(selectedScenario)
      setCompareResult(res.data)
    } catch (e) {
      alert(`Comparison failed: ${e.response?.data?.detail || e.message}`)
    } finally {
      setComparing(false)
    }
  }

  // Build comparison chart data
  const chartData = compareResult ? [
    {
      metric: 'Search Time (min)',
      B1: compareResult.comparison?.B1?.avg_search_time_min ?? 0,
      B2: compareResult.comparison?.B2?.avg_search_time_min ?? 0,
      B3: compareResult.comparison?.B3?.avg_search_time_min ?? 0,
      P: compareResult.comparison?.P?.avg_search_time_min ?? 0,
    },
    {
      metric: 'Wait Time (min)',
      B1: compareResult.comparison?.B1?.avg_wait_time_min ?? 0,
      B2: compareResult.comparison?.B2?.avg_wait_time_min ?? 0,
      B3: compareResult.comparison?.B3?.avg_wait_time_min ?? 0,
      P: compareResult.comparison?.P?.avg_wait_time_min ?? 0,
    },
    {
      metric: 'Avg Gate Queue',
      B1: compareResult.comparison?.B1?.avg_gate_queue ?? 0,
      B2: compareResult.comparison?.B2?.avg_gate_queue ?? 0,
      B3: compareResult.comparison?.B3?.avg_gate_queue ?? 0,
      P: compareResult.comparison?.P?.avg_gate_queue ?? 0,
    },
    {
      metric: 'Overflow Events',
      B1: compareResult.comparison?.B1?.overflow_events ?? 0,
      B2: compareResult.comparison?.B2?.overflow_events ?? 0,
      B3: compareResult.comparison?.B3?.overflow_events ?? 0,
      P: compareResult.comparison?.P?.overflow_events ?? 0,
    },
  ] : []

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-bold text-gray-800">Scenario Controls</h2>
        <p className="text-sm text-gray-500">Run parking simulations and compare strategies head-to-head</p>
      </div>

      {/* Controls */}
      <div className="bg-white rounded-lg shadow p-5">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Scenario</label>
            <select
              value={selectedScenario}
              onChange={e => setSelectedScenario(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            >
              {scenarios.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Strategy</label>
            <select
              value={selectedStrategy}
              onChange={e => setSelectedStrategy(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            >
              {strategies.map(s => (
                <option key={s.code} value={s.code}>{s.code} — {s.name}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="flex gap-3">
          <button
            onClick={runSimulation}
            disabled={loading}
            className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? '⏳ Running...' : '▶ Run Simulation'}
          </button>
          <button
            onClick={runComparison}
            disabled={comparing}
            className="px-4 py-2 bg-green-600 text-white rounded-md text-sm font-medium hover:bg-green-700 disabled:opacity-50"
          >
            {comparing ? '⏳ Comparing...' : '⚖️ Compare All Strategies'}
          </button>
        </div>
      </div>

      {/* Single sim result */}
      {simResult && (
        <div className="bg-white rounded-lg shadow p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">
            Simulation Result — {simResult.scenario} / {simResult.strategy}
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              ['Total Vehicles', simResult.vehicles],
              ['Parked', simResult.metrics?.parked_vehicles],
              ['Overflow Events', simResult.metrics?.overflow_events],
              ['Avg Search Time', simResult.metrics?.avg_search_time_min != null ? `${simResult.metrics.avg_search_time_min} min` : 'N/A'],
              ['Avg Wait Time', simResult.metrics?.avg_wait_time_min != null ? `${simResult.metrics.avg_wait_time_min} min` : 'N/A'],
              ['Avg Gate Queue', simResult.metrics?.avg_gate_queue ?? 'N/A'],
              ['Peak Gate Queue', simResult.metrics?.peak_gate_queue ?? 'N/A'],
              ['Run ID', simResult.run_id],
            ].map(([label, value]) => (
              <div key={label} className="p-3 bg-gray-50 rounded border border-gray-200">
                <div className="text-xs text-gray-500">{label}</div>
                <div className="text-lg font-bold text-gray-800">{value ?? 'N/A'}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Comparison chart */}
      {compareResult && (
        <div className="bg-white rounded-lg shadow p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">
            Strategy Comparison — {compareResult.scenario}
          </h3>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="metric" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              {['B1', 'B2', 'B3', 'P'].map(code => (
                <Bar key={code} dataKey={code} name={STRATEGY_LABELS[code]} fill={STRATEGY_COLORS[code]} />
              ))}
            </BarChart>
          </ResponsiveContainer>

          {/* Table */}
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-2 px-3 text-gray-500">Strategy</th>
                  <th className="text-right py-2 px-3 text-gray-500">Search Time</th>
                  <th className="text-right py-2 px-3 text-gray-500">Wait Time</th>
                  <th className="text-right py-2 px-3 text-gray-500">Avg Queue</th>
                  <th className="text-right py-2 px-3 text-gray-500">Overflow</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(compareResult.comparison || {}).map(([code, m]) => (
                  <tr key={code} className={`border-b ${code === 'P' ? 'bg-green-50 font-semibold' : ''}`}>
                    <td className="py-2 px-3">{STRATEGY_LABELS[code] || code}</td>
                    <td className="text-right py-2 px-3">{m.avg_search_time_min ?? '—'}</td>
                    <td className="text-right py-2 px-3">{m.avg_wait_time_min ?? '—'}</td>
                    <td className="text-right py-2 px-3">{m.avg_gate_queue ?? '—'}</td>
                    <td className="text-right py-2 px-3">{m.overflow_events ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
