import React from 'react'

// States what a forecast is: the campus time it is for, that it is a synthetic daily pattern,
// and whether recent live occupancy adjusted it. `basis` is `forecast_basis` from the API.
export default function ForecastBasis({ basis }) {
  if (!basis) return null
  const liveCount = basis.live_lots?.length ?? 0
  return (
    <div className="text-xs text-gray-500">
      Forecast for <strong>{String(basis.as_of).replace('T', ' ')}</strong> ({basis.timezone}) ·{' '}
      {basis.data || 'synthetic daily pattern'}
      {liveCount > 0
        ? ` · adjusted by recent live occupancy at ${liveCount} lot${liveCount > 1 ? 's' : ''}`
        : ' · no recent live occupancy, so this is the pattern only'}
    </div>
  )
}
