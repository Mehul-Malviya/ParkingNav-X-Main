import L from 'leaflet'

// Only used until /campus has loaded. Once it has, maps fit to the real node
// coordinates (see boundsOf), so this is NOT a source of truth for any location.
// The campus itself lives in configs/campus/vitap.yaml.
export const FALLBACK_CENTER = [16.4935, 80.4995]
export const FALLBACK_ZOOM = 16

// Coordinate convention across the app: {lat, lng} objects from the API, and
// [lat, lng] arrays for Leaflet. Never [lng, lat].
export function toLatLng(item) {
  return [item.lat, item.lng]
}

export function isCoord(p) {
  return Number.isFinite(p?.lat) && Number.isFinite(p?.lng)
}

// Bounds of every located campus feature, as [[lat, lng], ...] for fitBounds.
export function boundsOf(campus) {
  if (!campus) return []
  return [
    ...(campus.gates || []),
    ...(campus.parking_lots || []),
    ...(campus.destinations || []),
  ].filter(isCoord).map(toLatLng)
}

function segLen(a, b) {
  const dy = (b[0] - a[0]) * 111190
  const dx = (b[1] - a[1]) * 111320 * Math.cos((a[0] * Math.PI) / 180)
  return Math.hypot(dx, dy)
}

// Split a polyline at `dist` metres from its start: [head, tail] sharing the cut point.
function cutAt(points, dist) {
  let acc = 0
  for (let i = 0; i < points.length - 1; i++) {
    const len = segLen(points[i], points[i + 1])
    if (acc + len >= dist) {
      const t = len ? (dist - acc) / len : 0
      const [a, b] = [points[i], points[i + 1]]
      const cut = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
      return [[...points.slice(0, i + 1), cut], [cut, ...points.slice(i + 1)]]
    }
    acc += len
  }
  return [points, [points[points.length - 1]]]
}

// Separate the stretches at each end of a road that are not on a mapped road
// (access links: open ground or building interior) from the mapped part.
export function splitAccess(points, startM = 0, endM = 0) {
  let startLink = []
  let main = points
  if (startM > 0) [startLink, main] = cutAt(points, startM)
  let endLink = []
  if (endM > 0 && main.length > 1) {
    const [head, tail] = cutAt([...main].reverse(), endM)
    endLink = head.reverse()
    main = tail.reverse()
  }
  return { startLink, main, endLink }
}

// Human-readable provenance for popups. `item` is a gate/lot/destination from /campus.
export function positionNote(item) {
  if (item.coordinate_source === 'unplaced') return 'Position: not placed (no reference coordinates yet)'
  if (item.exact) return 'Position: exact (OpenStreetMap)'
  if (item.accuracy_m) {
    return `Position: approximate ±${item.accuracy_m} m (calibrated from reference map, not surveyed)`
  }
  return 'Position: source unknown'
}

export function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ))
}

// A marker whose anchor is exactly the coordinate: a dot centred on the point,
// with the text label hung below it. A pill anchored by a fixed pixel offset
// (the previous approach) drifts off the point because label widths vary.
//
// `approximate` positions (image-calibrated, not surveyed) get a hollow dashed dot and
// a "≈" label prefix so they can't be mistaken for exact OpenStreetMap positions.
export function pointLabelIcon({
  label, color, dotColor = color, textColor = 'white', emphasis = false, approximate = false,
}) {
  const size = emphasis ? 14 : 10
  const half = size / 2
  const dot = approximate
    ? `background:#fff;border:2px dashed ${dotColor}`
    : `background:${dotColor};border:2px solid #fff`
  const html = `
    <div style="position:relative;width:0;height:0;">
      <span style="position:absolute;left:${-half}px;top:${-half}px;width:${size}px;height:${size}px;border-radius:50%;${dot};box-sizing:border-box;box-shadow:0 1px 4px rgba(0,0,0,.5);"></span>
      <span style="position:absolute;left:0;top:${half + 2}px;transform:translateX(-50%);background:${color};color:${textColor};padding:${emphasis ? '3px 8px' : '2px 6px'};border-radius:${emphasis ? 5 : 10}px;font-size:${emphasis ? 11 : 10}px;font-weight:bold;white-space:nowrap;box-shadow:0 1px 4px rgba(0,0,0,.3);">${approximate ? '≈ ' : ''}${escapeHtml(label)}</span>
    </div>`
  return L.divIcon({ html, className: '', iconSize: [0, 0], iconAnchor: [0, 0], popupAnchor: [0, -half - 2] })
}
