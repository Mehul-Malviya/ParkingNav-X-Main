import React, { useState } from 'react'
import CampusMap from './components/CampusMap'
import ForecastPanel from './components/ForecastPanel'
import ScenarioControls from './components/ScenarioControls'
import RecommendationPanel from './components/RecommendationPanel'
import ExperimentsDashboard from './components/ExperimentsDashboard'
import FindParkingTab from './components/FindParkingTab'
import RecordCountsTab from './components/RecordCountsTab'

const TABS = [
  { id: 'map',        label: '🗺️ Digital Twin Map' },
  { id: 'find',       label: '🅿️ Find Parking' },
  { id: 'forecast',   label: '📈 Forecast & Risk' },
  { id: 'scenario',   label: '⚙️ Scenarios' },
  { id: 'recommend',  label: '💡 Recommendations' },
  { id: 'experiments',label: '🔬 Experiments' },
  { id: 'record',     label: '📝 Record Counts' },
]

export default function App() {
  const [activeTab, setActiveTab] = useState('map')
  const [pendingDest, setPendingDest] = useState(null)

  const handleNavigateTo = (dest) => {
    setPendingDest(dest)
    setActiveTab('find')
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-vitap-blue text-white shadow-md">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">ParkingNav-X</h1>
            <p className="text-xs text-blue-200">
              Event-Aware Predictive Digital Twin · VIT-AP University, Amaravati
            </p>
          </div>
          <div className="text-right text-xs text-blue-200">
            <div>B.Tech CSE Capstone 2026</div>
            <div className="text-vitap-gold font-semibold">LIVE DASHBOARD</div>
          </div>
        </div>
      </header>

      {/* Tab Navigation */}
      <nav className="bg-white border-b border-gray-200 shadow-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4">
          <div className="flex space-x-1 overflow-x-auto">
            {TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-3 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
                  activeTab === tab.id
                    ? 'border-vitap-blue text-vitap-blue'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </nav>

      {/* Content */}
      <main className="max-w-7xl mx-auto px-4 py-6">
        {activeTab === 'map'         && <CampusMap onNavigateTo={handleNavigateTo} />}
        {activeTab === 'find'        && <FindParkingTab initialDest={pendingDest} />}
        {activeTab === 'forecast'    && <ForecastPanel />}
        {activeTab === 'scenario'    && <ScenarioControls />}
        {activeTab === 'recommend'   && <RecommendationPanel />}
        {activeTab === 'experiments' && <ExperimentsDashboard />}
        {activeTab === 'record'      && <RecordCountsTab />}
      </main>

      <footer className="text-center text-xs text-gray-400 py-4 border-t border-gray-200 mt-8">
        ParkingNav-X · VIT-AP University, Amaravati · B.Tech CSE Capstone 2026
      </footer>
    </div>
  )
}
