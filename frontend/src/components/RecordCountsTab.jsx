import React, { useEffect, useState } from 'react'
import { api, getWriteKey, setWriteKey } from '../api'

// Local wall-clock time as the value a datetime-local input expects (YYYY-MM-DDTHH:mm).
const nowLocal = () => {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}

// Staff enter a real vehicle count for a lot. Stored as a real ("manual") reading, which adjusts that lot's
// live forecast for 30 minutes and trains the model once a lot has a week of readings.
export default function RecordCountsTab() {
  const [lots, setLots] = useState([])
  const [lotId, setLotId] = useState('')
  const [occupied, setOccupied] = useState('')
  const [when, setWhen] = useState(nowLocal())
  const [status, setStatus] = useState(null) // {ok, text}
  const [busy, setBusy] = useState(false)
  const [key, setKey] = useState(getWriteKey())

  useEffect(() => {
    api.getCampus().then(r => {
      const l = r.data.parking_lots ?? []
      setLots(l)
      if (l.length) setLotId(l[0].id)
    }).catch(() => setStatus({ ok: false, text: 'Could not load parking lots — is the backend running?' }))
  }, [])

  const lot = lots.find(l => l.id === lotId)
  const cap = lot?.usable_capacity

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      await api.recordObservation({
        timestamp: when, lot_id: lotId, occupied_spaces: Number(occupied), source: 'manual',
      })
      setStatus({ ok: true, text: `Saved: ${lot?.name} — ${occupied} of ${cap} spaces taken at ${when.replace('T', ' ')}.` })
      setOccupied('')
      setWhen(nowLocal())
    } catch (err) {
      setStatus({ ok: false, text: err.response?.status === 401 ? 'Wrong or missing access key.' : (err.response?.data?.detail || 'Could not save the count.') })
    } finally {
      setBusy(false)
    }
  }

  const retrain = async () => {
    setBusy(true)
    try {
      const r = (await api.retrainPredictor()).data
      setStatus({
        ok: true,
        text: r.real_lots.length
          ? `Forecast refitted. Real data used for ${r.real_lots.length} lot(s); the rest still use synthetic data.`
          : 'Forecast refitted. No lot has a week of real readings yet, so all lots still use synthetic data.',
      })
    } catch {
      setStatus({ ok: false, text: 'Retraining failed.' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-xl space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-gray-800">Record a parking count</h2>
        <p className="text-sm text-gray-500">
          Count the vehicles currently in a lot and enter the number. Times are campus time (IST).
        </p>
      </div>

      <form onSubmit={submit} className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 space-y-3">
        <label className="block text-sm">
          <span className="text-gray-600">Parking lot</span>
          <select value={lotId} onChange={e => setLotId(e.target.value)}
                  className="mt-1 w-full border border-gray-300 rounded px-2 py-1.5">
            {lots.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </label>
        <label className="block text-sm">
          <span className="text-gray-600">Vehicles parked now{cap ? ` (0–${cap})` : ''}</span>
          <input type="number" min="0" max={cap} required value={occupied}
                 onChange={e => setOccupied(e.target.value)}
                 className="mt-1 w-full border border-gray-300 rounded px-2 py-1.5" />
        </label>
        <label className="block text-sm">
          <span className="text-gray-600">Time of count</span>
          <input type="datetime-local" required value={when} onChange={e => setWhen(e.target.value)}
                 className="mt-1 w-full border border-gray-300 rounded px-2 py-1.5" />
        </label>
        <label className="block text-sm">
          <span className="text-gray-600">Access key <span className="text-gray-400">(only if the server requires one)</span></span>
          <input type="password" value={key} autoComplete="off"
                 onChange={e => { setKey(e.target.value); setWriteKey(e.target.value) }}
                 className="mt-1 w-full border border-gray-300 rounded px-2 py-1.5" />
        </label>
        <div className="flex gap-2">
          <button type="submit" disabled={busy || !lotId}
                  className="bg-vitap-blue text-white text-sm px-4 py-2 rounded disabled:opacity-50">
            Save count
          </button>
          <button type="button" onClick={retrain} disabled={busy}
                  className="border border-gray-300 text-gray-700 text-sm px-4 py-2 rounded disabled:opacity-50">
            Refit forecast
          </button>
        </div>
      </form>

      {status && (
        <div className={`text-sm rounded p-3 border ${status.ok
          ? 'bg-green-50 border-green-200 text-green-800' : 'bg-red-50 border-red-200 text-red-800'}`}>
          {status.text}
        </div>
      )}
      <p className="text-xs text-gray-400">
        A count adjusts that lot's forecast for 30 minutes. A lot's model trains on real data once it has a week of readings.
      </p>
    </div>
  )
}
