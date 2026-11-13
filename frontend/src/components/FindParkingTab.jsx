import React, { useEffect, useState } from 'react'
import {
  MapContainer, TileLayer, Marker, Popup, Polyline, Circle, Tooltip, useMap,
} from 'react-leaflet'
import L from 'leaflet'
import { api } from '../api'
import { FALLBACK_CENTER, FALLBACK_ZOOM, isCoord, positionNote } from '../mapConfig'
import 'leaflet/dist/leaflet.css'

delete L.Icon.Default.prototype._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
})

// Keeps the selected route in view. MapContainer's `center` prop only applies on
// first mount, so without this the map would not follow a changed selection.
function FitRoute({ points }) {
  const map = useMap()
  const key = JSON.stringify(points)
  useEffect(() => {
    if (points.length >= 2) map.fitBounds(points, { padding: [40, 40], maxZoom: 18 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, map])
  return null
}

function fillColor(rate) {
  if (rate >= 0.90) return '#ef4444'
  if (rate >= 0.70) return '#f97316'
  if (rate >= 0.50) return '#eab308'
  return '#22c55e'
}

// Fixed 24x24 box so the pin tip (bottom centre) sits exactly on the coordinate,
// regardless of how wide the emoji glyph renders.
function starIcon() {
  return L.divIcon({
    html: `<div style="width:24px;height:24px;font-size:22px;line-height:24px;text-align:center;">📍</div>`,
    className: '',
    iconSize: [24, 24],
    iconAnchor: [12, 24],
    popupAnchor: [0, -24],
  })
}

function parkingIcon(rank) {
  const colors = ['#16a34a', '#2563eb', '#9333ea', '#ea580c', '#6b7280']
  const c = colors[Math.min(rank, colors.length - 1)]
  return L.divIcon({
    html: `<div style="background:${c};color:white;border-radius:50%;width:26px;height:26px;display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:13px;box-shadow:0 2px 6px rgba(0,0,0,0.4);">${rank + 1}</div>`,
    className: '',
    iconAnchor: [13, 13],
  })
}

export default function FindParkingTab({ initialDest }) {
  const [campus, setCampus] = useState(null)
  const [selectedDest, setSelectedDest] = useState('')
  const [selectedGate, setSelectedGate] = useState('vitap-gate-main')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [selectedOption, setSelectedOption] = useState(0)

  useEffect(() => {
      let cancelled = false

      const loadCampus = async () => {
        setError(null)

        try {
          const res = await api.getCampus()

          if (cancelled) return

          setCampus(res.data)

          // Only select a destination that still exists in the freshly loaded campus; a
          // stale id (e.g. a destination removed from the config) must never be requested.
          const available = res.data.destinations || []
          const wanted = initialDest && available.find(d => d.id === initialDest.id)
          setSelectedDest(wanted ? wanted.id : (available[0]?.id ?? ''))
        } catch (e) {
          if (cancelled) return

          setError(
            e.response?.data?.detail ||
            e.message ||
            'Failed to load campus data.'
          )
        }
      }

      loadCampus()

      return () => {
        cancelled = true
      }
    }, [initialDest])

  const findParking = async () => {
    if (!selectedDest) return
    if (campus && !campus.destinations?.some(d => d.id === selectedDest)) {
      setError('This destination no longer exists. Reload the page to refresh the destination list.')
      return
    }
    setLoading(true)
    setResult(null)
    setError(null)
    try {
      const res = await api.findParking(selectedDest, selectedGate)
      setResult(res.data)
      setSelectedOption(0)
    } catch (e) {
      setError(
        e.response?.status === 404
          ? 'That destination is no longer available. Reload the page to refresh the destination list.'
          : (e.response?.data?.detail || e.message || 'Failed to find parking')
      )
    } finally {
      setLoading(false)
    }
  }

  const option = result?.options?.[selectedOption]
  const destNode = campus?.destinations?.find(d => d.id === selectedDest)

  // Build map center from destination or default
  const mapCenter = isCoord(destNode)
    ? [destNode.lat, destNode.lng]
    : FALLBACK_CENTER

  // Route geometry for display
  const driveCoords = option?.drive_route?.geometry?.map(p => [p.lat, p.lng]) || []
  const walkCoords = option?.walk_route?.geometry?.map(p => [p.lat, p.lng]) || []
  const lotCoords = option ? [
    campus?.parking_lots?.find(l => l.id === option.lot_id)?.lat,
    campus?.parking_lots?.find(l => l.id === option.lot_id)?.lng,
  ] : null

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-bold text-gray-800">Find Parking</h2>
        <p className="text-sm text-gray-500">
          Choose your destination and entry gate — ParkingNav-X recommends the best available lot with drive + walk route.
        </p>
      </div>

      {/* Input controls */}
      <div className="bg-white rounded-lg shadow p-5">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Destination</label>
            <select
              value={selectedDest}
              onChange={e => setSelectedDest(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            >
              {(campus?.destinations || []).map(d => (
                <option key={d.id} value={d.id}>
                  {d.name} ({d.category?.replace(/_/g, ' ')})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Entry Gate</label>
            <select
              value={selectedGate}
              onChange={e => setSelectedGate(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            >
              {(campus?.gates || []).map(g => (
                <option key={g.id} value={g.id} disabled={g.status !== 'open'}>
                  {g.name} {g.status !== 'open' ? '(closed)' : ''}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-end">
            <button
              onClick={findParking}
              disabled={loading || !selectedDest}
              className="w-full px-4 py-2 bg-blue-700 text-white rounded-md text-sm font-semibold hover:bg-blue-800 disabled:opacity-50 transition-colors"
            >
              {loading ? '⏳ Finding…' : '🅿️ Find Best Parking'}
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
          ⚠️ {error}
        </div>
      )}

      {result && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Options list */}
          <div className="space-y-3">
            <div className="text-sm font-semibold text-gray-600">
              {result.options_count} options found for <strong>{result.destination_name}</strong>
            </div>
            {result.options.map((opt, idx) => (
              <button
                key={opt.lot_id}
                onClick={() => setSelectedOption(idx)}
                className={`w-full text-left p-3 rounded-lg border-2 transition-all ${
                  idx === selectedOption
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-200 bg-white hover:border-gray-300'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className={`w-6 h-6 rounded-full text-white text-xs flex items-center justify-center font-bold ${
                    idx === 0 ? 'bg-green-600' : idx === 1 ? 'bg-blue-600' : 'bg-gray-500'
                  }`}>{idx + 1}</span>
                  <span className="text-sm font-semibold text-gray-800 leading-tight">{opt.lot_name}</span>
                  {opt.is_preferred_for_destination && (
                    <span className="ml-auto text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded">⭐ Recommended</span>
                  )}
                </div>
                <div className="text-xs text-gray-600 space-y-0.5 ml-8">
                  <div>🚗 {opt.drive_time_minutes} min drive · 🚶 {opt.walk_time_minutes} min walk</div>
                  <div>
                    Fill:
                    <span className="font-semibold ml-1" style={{ color: fillColor(opt.predicted_fill_rate) }}>
                      {opt.predicted_fill_pct}%
                    </span>
                    · ~{opt.estimated_available} spaces free
                  </div>
                  <div className="text-gray-500 italic text-xs leading-tight">{opt.recommendation_reason}</div>
                </div>
              </button>
            ))}
            <div className="text-xs text-gray-400 italic">
              Based on the XGBoost fill forecast; the map tab states whether it was trained on real or synthetic data.
            </div>
          </div>

          {/* Map + detail */}
          <div className="lg:col-span-2 space-y-3">
            {destNode && !isCoord(destNode) && (
              <div className="p-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-800">
                {destNode.name} has no reference coordinates yet, so it is not drawn on the map.
                Lot ranking and walk times still use the routing graph.
              </div>
            )}
            {/* Map */}
            <div className="rounded-lg overflow-hidden border border-gray-200 shadow" style={{ height: 340 }}>
              <MapContainer center={mapCenter} zoom={FALLBACK_ZOOM} style={{ height: '100%', width: '100%' }}>
                <TileLayer
                  attribution='&copy; OpenStreetMap'
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                <FitRoute points={[...driveCoords, ...walkCoords]} />

                {/* All parking lot markers */}
                {result.options.map((opt, idx) => {
                  const lot = campus?.parking_lots?.find(l => l.id === opt.lot_id)
                  if (!lot) return null
                  return (
                    <Marker
                      key={opt.lot_id}
                      position={[lot.lat, lot.lng]}
                      icon={parkingIcon(idx)}
                    >
                      <Tooltip permanent direction="top" offset={[0, -14]}>
                        <span className="text-xs font-medium">{lot.name.replace(' Lot','').replace(' Parking','')}</span>
                      </Tooltip>
                      <Popup>
                        <div className="text-sm">
                          <strong>{lot.name}</strong><br />
                          Fill: {opt.predicted_fill_pct}%<br />
                          ~{opt.estimated_available} spaces free<br />
                          Total time: {opt.total_time_minutes} min
                        </div>
                      </Popup>
                    </Marker>
                  )
                })}

                {/* Destination marker */}
                {isCoord(destNode) && (
                  <Marker position={[destNode.lat, destNode.lng]} icon={starIcon()}>
                    <Popup>
                      <strong>📍 {destNode.name}</strong><br />
                      {destNode.category?.replace(/_/g, ' ')}<br />
                      <span className="text-xs text-gray-500">{positionNote(destNode)}</span>
                    </Popup>
                  </Marker>
                )}

                {/* Drive route — blue */}
                {driveCoords.length >= 2 && (
                  <Polyline
                    positions={driveCoords}
                    pathOptions={{ color: '#2563eb', weight: 5, opacity: 0.85 }}
                  >
                    <Tooltip sticky><span className="text-xs">🚗 Drive route ({option.drive_time_minutes} min)</span></Tooltip>
                  </Polyline>
                )}

                {/* Walk route — green dashed */}
                {walkCoords.length >= 2 && (
                  <Polyline
                    positions={walkCoords}
                    pathOptions={{ color: '#16a34a', weight: 4, opacity: 0.85, dashArray: '8 5' }}
                  >
                    <Tooltip sticky><span className="text-xs">🚶 Walk route ({option.walk_time_minutes} min)</span></Tooltip>
                  </Polyline>
                )}
              </MapContainer>
            </div>

            {/* Route detail card */}
            {option && (
              <div className="bg-white rounded-lg border border-gray-200 shadow p-4">
                <div className="flex items-center gap-2 mb-3">
                  <span className="w-7 h-7 rounded-full bg-green-600 text-white text-sm flex items-center justify-center font-bold">
                    {selectedOption + 1}
                  </span>
                  <div>
                    <div className="font-bold text-gray-800">{option.lot_name}</div>
                    <div className="text-xs text-gray-500">Recommended parking for {result.destination_name}</div>
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                  {[
                    ['🚗 Drive', `${option.drive_time_minutes} min`, 'text-blue-700'],
                    ['🚶 Walk', `${option.walk_time_minutes} min`, 'text-green-700'],
                    ['⏱️ Total', `${option.total_time_minutes} min`, 'text-gray-700'],
                    ['🅿️ Forecast', `${option.predicted_fill_pct}%`, option.predicted_fill_rate >= 0.9 ? 'text-red-600' : option.predicted_fill_rate >= 0.7 ? 'text-orange-500' : 'text-green-600'],
                  ].map(([label, value, cls]) => (
                    <div key={label} className="text-center p-2 bg-gray-50 rounded border">
                      <div className={`text-lg font-bold ${cls}`}>{value}</div>
                      <div className="text-xs text-gray-500">{label}</div>
                    </div>
                  ))}
                </div>

                <div className="space-y-2">
                  <div className="flex items-start gap-2 text-sm">
                    <span className="mt-0.5 w-5 h-5 rounded-full bg-blue-600 text-white text-xs flex items-center justify-center flex-shrink-0">1</span>
                    <div>
                      <div className="font-medium text-gray-700">Drive to {option.lot_name}</div>
                      <div className="text-xs text-gray-500">
                        Enter via {campus?.gates?.find(g => g.id === result.gate_used)?.name || result.gate_used}
                        · {option.drive_route.distance_meters}m · {option.drive_time_minutes} min
                      </div>
                    </div>
                  </div>
                  <div className="flex items-start gap-2 text-sm">
                    <span className="mt-0.5 w-5 h-5 rounded-full bg-green-600 text-white text-xs flex items-center justify-center flex-shrink-0">2</span>
                    <div>
                      <div className="font-medium text-gray-700">Walk to {result.destination_name}</div>
                      <div className="text-xs text-gray-500">
                        {option.walk_route.distance_meters}m walking path · {option.walk_time_minutes} min
                      </div>
                    </div>
                  </div>
                  <div className="mt-2 p-2 bg-yellow-50 border border-yellow-200 rounded text-xs text-yellow-800">
                    💡 {option.recommendation_reason}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!result && !loading && !error && (
        <div className="text-center py-12 text-gray-400">
          <div className="text-5xl mb-4">🅿️</div>
          <div className="text-lg font-medium">Select your destination and click Find Best Parking</div>
          <div className="text-sm mt-1">ParkingNav-X will compute drive + walk routes and rank parking options by predicted fill rate</div>
        </div>
      )}
    </div>
  )
}
