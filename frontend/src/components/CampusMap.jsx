import React, { useEffect, useState, useCallback } from 'react'
import {
  MapContainer, TileLayer, Marker, Popup, Circle,
  Tooltip, Polyline, Polygon, useMap,
} from 'react-leaflet'
import L from 'leaflet'
import { api } from '../api'
import ForecastBasis from './ForecastBasis'
import { FALLBACK_CENTER, FALLBACK_ZOOM, boundsOf, isCoord, pointLabelIcon, positionNote, splitAccess } from '../mapConfig'
import 'leaflet/dist/leaflet.css'

// Fix Leaflet default icon
delete L.Icon.Default.prototype._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
})

function fillColor(rate) {
  if (rate >= 0.90) return '#ef4444'
  if (rate >= 0.70) return '#f97316'
  if (rate >= 0.50) return '#eab308'
  return '#22c55e'
}

function categoryColor(cat) {
  if (!cat) return '#6b7280'
  if (cat.includes('academic')) return '#3b82f6'
  if (cat.includes('hostel')) return '#8b5cf6'
  if (cat.includes('cafeteria') || cat.includes('food')) return '#f59e0b'
  if (cat.includes('sports')) return '#10b981'
  if (cat.includes('admin')) return '#6366f1'
  return '#6b7280'
}

// Dashed ring whose radius is the real positional uncertainty (metres), only for
// approximate points. Leaflet sizes Circle in metres, so it scales with zoom.
function AccuracyRing({ item }) {
  if (!isCoord(item) || item.exact || !item.accuracy_m) return null
  return (
    <Circle
      center={[item.lat, item.lng]}
      radius={item.accuracy_m}
      interactive={false}
      pathOptions={{ color: '#6b7280', weight: 1, dashArray: '3 4', fillColor: '#9ca3af', fillOpacity: 0.08 }}
    />
  )
}

function categoryIcon(cat, name, approximate) {
  const emoji = cat?.includes('hostel') ? '🏠'
    : cat?.includes('academic') ? '🎓'
    : cat?.includes('food') || cat?.includes('cafeteria') ? '🍽️'
    : cat?.includes('sports') ? '⚽'
    : cat?.includes('admin') ? '🏛️'
    : cat?.includes('library') ? '📚'
    : '📍'
  return pointLabelIcon({
    label: `${emoji} ${name.length > 12 ? name.slice(0, 12) + '…' : name}`,
    color: categoryColor(cat),
    approximate,
  })
}

function gateIcon(name, status, approximate) {
  return pointLabelIcon({
    label: `${status === 'open' ? '🚗' : '🚫'} ${name}`,
    color: '#003087',
    emphasis: true,
    approximate,
  })
}

// Fits the view to the campus once, and again only if the located features
// themselves change. campus is re-fetched every 30 s; keying on the bounds
// (not the campus object) stops that refresh from resetting the user's pan/zoom.
function FitBounds({ campus }) {
  const map = useMap()
  const pts = boundsOf(campus)
  const key = JSON.stringify(pts)
  useEffect(() => {
    if (pts.length > 0) map.fitBounds(pts, { padding: [30, 30] })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, map])
  return null
}

export default function CampusMap({ onNavigateTo }) {
  const [campus, setCampus] = useState(null)
  const [predictions, setPredictions] = useState([])
  const [forecastBasis, setForecastBasis] = useState(null)
  const [forecastSource, setForecastSource] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [showRoads, setShowRoads] = useState(true)
  const [showDests, setShowDests] = useState(true)
  const [highlightRoute, setHighlightRoute] = useState(null) // [{lat,lng}]

  const fetchData = useCallback(async () => {
    setLoading(true)

    try {
      const [campusResult, predictionResult] = await Promise.allSettled([
        api.getCampus(),
        api.predictAll(15),
      ])

      const errors = []

      if (campusResult.status === 'fulfilled') {
        setCampus(campusResult.value.data)
      } else {
        errors.push(
          `Campus: ${
            campusResult.reason.response?.data?.detail ||
            campusResult.reason.message ||
            'Request failed'
          }`
        )
      }

      if (predictionResult.status === 'fulfilled') {
        setPredictions(predictionResult.value.data.predictions ?? [])
        setForecastBasis(predictionResult.value.data.forecast_basis ?? null)
        setForecastSource(predictionResult.value.data.data_source ?? null)
      } else {
        setPredictions([])
        errors.push(
          `Predictions: ${
            predictionResult.reason.response?.data?.detail ||
            predictionResult.reason.message ||
            'Request failed'
          }`
        )
      }

      setError(errors.length ? errors.join(' | ') : null)
      setLastUpdated(new Date().toLocaleTimeString())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [fetchData])

  const predMap = {}
  predictions.forEach(p => { predMap[p.lot_id] = p })

  // Build road polylines from campus data
  const roadLines = (campus?.roads || []).filter(r => r.status === 'open' && r.geometry?.length >= 2)

  return (
    <div>
      {/* Header + controls */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div>
          <h2 className="text-lg font-bold text-gray-800">VIT-AP Campus Digital Twin</h2>
          <p className="text-sm text-gray-500">15-min occupancy forecast · Live road network · Click any destination</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <label className="flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer">
            <input type="checkbox" checked={showRoads} onChange={e => setShowRoads(e.target.checked)} />
            Roads
          </label>
          <label className="flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer">
            <input type="checkbox" checked={showDests} onChange={e => setShowDests(e.target.checked)} />
            Destinations
          </label>
          {lastUpdated && <span className="text-xs text-gray-400">Updated: {lastUpdated}</span>}
          <button onClick={fetchData} className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
          ⚠️ {error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Map */}
        <div className="lg:col-span-2 rounded-lg overflow-hidden border border-gray-200 shadow" style={{ height: 480 }}>
          <MapContainer center={FALLBACK_CENTER} zoom={FALLBACK_ZOOM} style={{ height: '100%', width: '100%' }}>
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {campus && <FitBounds campus={campus} />}

            {/* Road network. Stretches not on a mapped road (access links) are dotted. */}
            {showRoads && roadLines.map(road => {
              const positions = road.geometry.map(pt => [pt.lat, pt.lng])
              const { startLink, main, endLink } = splitAccess(
                positions, road.access_start_m || 0, road.access_end_m || 0)
              const isDrive = road.is_driveable
              const color = isDrive ? '#3b82f6' : '#94a3b8'
              return (
                <React.Fragment key={road.id}>
                  {main.length >= 2 && (
                    <Polyline
                      positions={main}
                      pathOptions={{
                        color,
                        weight: isDrive ? 3 : 1.5,
                        opacity: isDrive ? 0.7 : 0.5,
                        dashArray: isDrive ? null : '4 4',
                      }}
                    >
                      <Tooltip sticky>
                        <span className="text-xs">{road.name} · {road.length_meters}m · {Math.round(road.travel_time_seconds/60)}min</span>
                      </Tooltip>
                    </Polyline>
                  )}
                  {[startLink, endLink].map((link, i) => link.length >= 2 && (
                    <Polyline
                      key={`${road.id}-access-${i}`}
                      positions={link}
                      pathOptions={{ color: '#64748b', weight: 2, opacity: 0.9, dashArray: '1 6', lineCap: 'round' }}
                    >
                      <Tooltip sticky>
                        <span className="text-xs">Access link: no mapped road here ({road.name})</span>
                      </Tooltip>
                    </Polyline>
                  ))}
                </React.Fragment>
              )
            })}

            {/* Highlighted route */}
            {highlightRoute && highlightRoute.length >= 2 && (
              <Polyline
                positions={highlightRoute.map(pt => [pt.lat, pt.lng])}
                pathOptions={{ color: '#f59e0b', weight: 5, opacity: 0.9 }}
              />
            )}

            {/* Parking lots. A lot with a real (OpenStreetMap) footprint is drawn as that footprint
                only; a 55 m circle would cover the footprints and the nearby gate. Lots without a
                footprint get a circle at their (approximate) centre. Placeholder boxes are never drawn. */}
            {(campus?.parking_lots || []).map(lot => {
              const pred = predMap[lot.id]
              const fill = pred ? pred.predicted_fill_rate : 0.4
              const shortName = lot.name.replace(' Lot', '').replace(' Parking', '')
              const label = (
                <div className="text-xs font-semibold">
                  {shortName}<br />
                  <span style={{ color: fillColor(fill) }}>{(fill * 100).toFixed(0)}%</span>
                </div>
              )
              const popup = (
                <div className="text-sm min-w-40">
                  <strong className="text-blue-800">{lot.name}</strong><br />
                  <span className="text-gray-500">Status: </span>
                  <span className={lot.status === 'open' ? 'text-green-600' : 'text-red-600'}>{lot.status}</span><br />
                  Usable: <strong>{lot.usable_capacity}</strong> spaces<br />
                  Forecast (15m): <strong style={{ color: fillColor(fill) }}>{(fill * 100).toFixed(1)}%</strong><br />
                  {pred && (
                    <>
                      90% CI: [{(pred.lower_90 * 100).toFixed(0)}%, {(pred.upper_90 * 100).toFixed(0)}%]<br />
                      Model: <em>{pred.model || '—'}</em><br />
                      {pred.proactive_alert && <span className="text-red-600 font-bold">⚠️ OVERFLOW RISK</span>}
                    </>
                  )}
                  <div className="mt-1 text-xs text-gray-400">
                    {pred?.trained_on === 'real' ? 'Trained on recorded occupancy' : '[SYNTHETIC data — not real occupancy]'}
                  </div>
                  <div className="mt-1 text-xs text-gray-500">{positionNote(lot)}</div>
                </div>
              )
              const hasFootprint = (lot.boundary || []).length > 0
              return (
                <React.Fragment key={lot.id}>
                  {hasFootprint ? (
                    // Each footprint carries its own label, placed below it (away from any gate above).
                    lot.boundary.map((ring, i) => (
                      <Polygon
                        key={`${lot.id}-b${i}`}
                        positions={ring.map(p => [p.lat, p.lng])}
                        pathOptions={{
                          color: fill >= 0.90 ? '#dc2626' : '#1d4ed8',
                          weight: 2.5,
                          fillColor: fillColor(fill),
                          fillOpacity: 0.6,
                        }}
                      >
                        <Tooltip permanent direction="bottom" offset={[0, 6]}>{label}</Tooltip>
                        <Popup>{popup}</Popup>
                      </Polygon>
                    ))
                  ) : (
                    <>
                      <AccuracyRing item={lot} />
                      <Circle
                        center={[lot.lat, lot.lng]}
                        radius={55}
                        pathOptions={{
                          fillColor: fillColor(fill),
                          fillOpacity: 0.8,
                          color: fill >= 0.90 ? '#dc2626' : '#1d4ed8',
                          weight: 2.5,
                        }}
                      >
                        <Tooltip permanent direction="top" offset={[0, -22]}>{label}</Tooltip>
                        <Popup>{popup}</Popup>
                      </Circle>
                    </>
                  )}
                </React.Fragment>
              )
            })}

            {/* Gate markers */}
            {(campus?.gates || []).map(gate => (
              <React.Fragment key={gate.id}>
                <AccuracyRing item={gate} />
                <Marker
                  position={[gate.lat, gate.lng]}
                  icon={gateIcon(gate.name, gate.status, !gate.exact)}
                >
                  <Popup>
                    <div className="text-sm">
                      <strong>{gate.name}</strong><br />
                      Throughput: {gate.capacity} veh/min<br />
                      Status: <span className={gate.status === 'open' ? 'text-green-600' : 'text-red-600'}>{gate.status}</span>
                      <div className="mt-1 text-xs text-gray-500">{positionNote(gate)}</div>
                    </div>
                  </Popup>
                </Marker>
              </React.Fragment>
            ))}

            {/* Destination markers */}
            {showDests && (campus?.destinations || []).filter(isCoord).map(dest => (
              <React.Fragment key={dest.id}>
              <AccuracyRing item={dest} />
              <Marker
                position={[dest.lat, dest.lng]}
                icon={categoryIcon(dest.category, dest.name, !dest.exact)}
              >
                <Popup>
                  <div className="text-sm min-w-36">
                    <strong className="text-gray-800">{dest.name}</strong><br />
                    <span className="text-gray-500 capitalize">{dest.category?.replace(/_/g, ' ')}</span><br />
                    {dest.nearest_lots?.length > 0 && (
                      <span className="text-xs text-gray-400">Nearest lots: {dest.nearest_lots.length}</span>
                    )}
                    <div className="mt-1 text-xs text-gray-500">{positionNote(dest)}</div>
                    {onNavigateTo && (
                      <button
                        onClick={() => onNavigateTo(dest)}
                        className="mt-2 w-full px-2 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700"
                      >
                        🅿️ Find Parking Here
                      </button>
                    )}
                  </div>
                </Popup>
              </Marker>
              </React.Fragment>
            ))}
          </MapContainer>
        </div>

        {/* Sidebar */}
        <div className="space-y-3 overflow-y-auto" style={{ maxHeight: 480 }}>
          {/* Stats summary */}
          {campus && (
            <div className="p-3 bg-blue-50 rounded-lg border border-blue-200">
              <div className="text-xs font-bold text-blue-700 mb-2">Campus Overview</div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="text-center p-2 bg-white rounded border">
                  <div className="text-lg font-bold text-blue-700">{campus.parking_lots?.length || 0}</div>
                  <div className="text-gray-500">Parking Zones</div>
                </div>
                <div className="text-center p-2 bg-white rounded border">
                  <div className="text-lg font-bold text-green-700">
                    {campus.parking_lots?.reduce((s, l) => s + (l.usable_capacity || 0), 0)}
                  </div>
                  <div className="text-gray-500">Total Spaces</div>
                </div>
                <div className="text-center p-2 bg-white rounded border">
                  <div className="text-lg font-bold text-purple-700">{campus.destinations?.length || 0}</div>
                  <div className="text-gray-500">Destinations</div>
                </div>
                <div className="text-center p-2 bg-white rounded border">
                  <div className="text-lg font-bold text-gray-700">{campus.roads?.length || 0}</div>
                  <div className="text-gray-500">Road Segments</div>
                </div>
              </div>
            </div>
          )}

          {/* Lot cards */}
          <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Parking Lots</div>
          <ForecastBasis basis={forecastBasis} />
          {loading && <div className="text-sm text-gray-400">Loading…</div>}
          {(campus?.parking_lots || []).map(lot => {
            const pred = predMap[lot.id]
            const fill = pred ? pred.predicted_fill_rate : 0
            return (
              <div
                key={lot.id}
                className={`p-3 border rounded-lg text-sm ${
                  fill >= 0.90 ? 'border-red-300 bg-red-50'
                  : fill >= 0.70 ? 'border-orange-200 bg-orange-50'
                  : 'border-gray-200 bg-white'
                }`}
              >
                <div className="flex justify-between items-start mb-1">
                  <div className="font-medium text-gray-800 text-xs leading-tight">{lot.name}</div>
                  {pred?.proactive_alert && <span className="text-red-600 text-xs font-bold ml-1">⚠️</span>}
                </div>
                <div className="flex justify-between text-xs text-gray-500 mb-1">
                  <span>15-min forecast</span>
                  <span className="font-semibold" style={{ color: fillColor(fill) }}>
                    {fill ? (fill * 100).toFixed(0) : '—'}%
                  </span>
                </div>
                <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${(fill || 0) * 100}%`, backgroundColor: fillColor(fill) }}
                  />
                </div>
                <div className="text-xs text-gray-400 mt-1">
                  {lot.usable_capacity} spaces · {lot.status}
                </div>
              </div>
            )
          })}

          {/* Legend */}
          <div className="p-2 bg-gray-50 rounded border border-gray-200 text-xs">
            <div className="font-semibold text-gray-500 mb-1.5">Map Legend</div>
            <div className="space-y-1">
              {[['< 50%', '#22c55e'], ['50–70%', '#eab308'], ['70–90%', '#f97316'], ['> 90%', '#ef4444']].map(([l, c]) => (
                <div key={l} className="flex items-center gap-2 text-gray-600">
                  <div className="w-3 h-3 rounded-full flex-shrink-0" style={{ background: c }} />
                  {l} full
                </div>
              ))}
              <div className="flex items-center gap-2 text-gray-600 mt-1">
                <div className="w-6 h-0.5 flex-shrink-0" style={{ background: '#3b82f6' }} />
                Driveable road
              </div>
              <div className="flex items-center gap-2 text-gray-600">
                <div className="w-6 border-t border-dashed border-gray-400 flex-shrink-0" />
                Walking path
              </div>
              <div className="flex items-center gap-2 text-gray-600">
                <div className="w-6 border-t-2 border-dotted border-slate-500 flex-shrink-0" />
                Access link (no mapped road)
              </div>
              <div className="flex items-center gap-2 text-gray-600 mt-1">
                <div className="w-3 h-3 rounded-full flex-shrink-0 bg-gray-600 border-2 border-white" />
                Exact position (OpenStreetMap)
              </div>
              <div className="flex items-center gap-2 text-gray-600">
                <div className="w-3 h-3 rounded-full flex-shrink-0 bg-white border-2 border-dashed border-gray-600" />
                ≈ Approximate (±25 m, not surveyed)
              </div>
            </div>
          </div>
          <div className="text-xs text-gray-400 italic">
            {forecastSource || '[SYNTHETIC] Forecast from XGBoost model. Not real occupancy data.'}
          </div>
        </div>
      </div>
    </div>
  )
}
