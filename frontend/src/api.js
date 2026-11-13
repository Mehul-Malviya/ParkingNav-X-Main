import axios from 'axios'

const BASE = '/api'

// Write key for a live deployment (PARKINGNAV_API_KEY on the server); kept for this browser tab only.
export const getWriteKey = () => { try { return sessionStorage.getItem('writeKey') || '' } catch { return '' } }
export const setWriteKey = (k) => { try { sessionStorage.setItem('writeKey', k) } catch { /* private mode */ } }
const keyHeader = () => (getWriteKey() ? { headers: { 'X-API-Key': getWriteKey() } } : {})

export const api = {
  // Info
  getRoot:           () => axios.get(`${BASE}/`),

  // Campus
  getCampus:         () => axios.get(`${BASE}/campus`),
  getCampusGraph:    () => axios.get(`${BASE}/campus/graph`),
  getEvents:         () => axios.get(`${BASE}/events`),

  // Simulation
  getScenarios:      () => axios.get(`${BASE}/scenarios`),
  getStrategies:     () => axios.get(`${BASE}/strategies`),
  simulate:          (scenario, strategy) =>
    axios.post(`${BASE}/simulate`, { scenario, strategy }),
  compareStrategies: (scenario) =>
    axios.get(`${BASE}/compare/${scenario}`),

  // Prediction
  predictOccupancy:  (lot_id, horizon_minutes = 15) =>
    axios.get(`${BASE}/predict/occupancy`, { params: { lot_id, horizon_minutes } }),
  predictAll:        (horizon_minutes = 15) =>
    axios.get(`${BASE}/predict/all`, { params: { horizon_minutes } }),

  // Real occupancy counts
  recordObservation: (obs) => axios.post(`${BASE}/observations`, obs, keyHeader()),
  retrainPredictor:  () => axios.post(`${BASE}/predict/retrain`, null, keyHeader()),

  // Risk
  getRiskCurrent:    () => axios.get(`${BASE}/risk/current`),
  getRiskForecast:   (horizon = 15) =>
    axios.get(`${BASE}/risk/forecast`, { params: { horizon } }),

  // Optimization
  optimize:          (scenario = 'E1_normal_day', weight_profile = 'P1') =>
    axios.post(`${BASE}/optimize`, { scenario, weight_profile }),
  getRecommendations: () => axios.get(`${BASE}/recommendations`),
  getOptimizeProfiles: () => axios.get(`${BASE}/optimize/profiles`),

  // Routing
  getRoute:          (origin, destination, mode = 'drive') =>
    axios.get(`${BASE}/route`, { params: { origin, destination, mode } }),
  findParking:       (destination_id, gate_id = 'vitap-gate-main') =>
    axios.get(`${BASE}/find_parking`, { params: { destination_id, gate_id } }),

  // Experiments
  getExperimentResults: (scenario, strategy, limit = 200) =>
    axios.get(`${BASE}/experiments/results`, { params: { scenario, strategy, limit } }),
  getExperimentSummary: () => axios.get(`${BASE}/experiments/summary`),
  runExperiment: (scenario, strategies, seeds) =>
    axios.post(`${BASE}/experiments/run`, { scenario, strategies, seeds }),
}
