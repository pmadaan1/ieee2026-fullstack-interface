import { useState, useEffect } from 'react';
import GaitCard from './components/GaitCard';
import MetricCard from './components/MetricCard';
import CadenceTrend from './components/CadenceTrend';
import './App.css';

const MAX_POINTS = 20;
const WS_URL   = 'ws://localhost:8000/ws';
const SCAN_URL = 'http://localhost:8000/scan';

function formatTime(date) {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export default function App() {
  const [connected, setConnected] = useState(false);
  const [scanning, setScanning]   = useState(false);
  const [cadence, setCadence]     = useState(null);
  const [steps, setSteps]         = useState(null);
  const [clearance, setClearance] = useState(null);
  const [similarity, setSimilarity] = useState(null);
  const [gait, setGait]           = useState({ classification: 'Normal', confidence: null });
  const [cadenceHistory, setCadenceHistory] = useState({ values: [], labels: [] });

  useEffect(() => {
    let ws;
    let reconnectTimeout;

    function connect() {
      ws = new WebSocket(WS_URL);

      ws.onmessage = (event) => {
        const { connected: isConnected, scanning: isScanning, metrics: m } = JSON.parse(event.data);
        setConnected(isConnected);
        setScanning(isScanning);

        if (!isConnected) return;

        setCadence(m.cadence);
        setSteps(m.steps);
        setClearance(m.clearance);
        setSimilarity(m.similarity);

        if (m.classification !== null) {
          setGait({ classification: m.classification, confidence: m.confidence });
        }

        if (m.cadence !== null) {
          setCadenceHistory(prev => ({
            values: [...prev.values.slice(-(MAX_POINTS - 1)), m.cadence],
            labels: [...prev.labels.slice(-(MAX_POINTS - 1)), formatTime(new Date())],
          }));
        }
      };

      ws.onclose = () => {
        setConnected(false);
        reconnectTimeout = setTimeout(connect, 3000);
      };

      ws.onerror = () => ws.close();
    }

    connect();
    return () => {
      clearTimeout(reconnectTimeout);
      ws?.close();
    };
  }, []);

  async function handleScan() {
    await fetch(SCAN_URL, { method: 'POST' });
  }

  const avgCadence = cadenceHistory.values.length
    ? Math.round(cadenceHistory.values.reduce((s, v) => s + v, 0) / cadenceHistory.values.length)
    : null;

  const cadenceDiff = cadence !== null && avgCadence !== null ? cadence - avgCadence : null;
  const cadenceDelta = cadenceDiff === null ? null
    : cadenceDiff === 0 ? 'at average'
    : `${cadenceDiff > 0 ? '+' : ''}${cadenceDiff} from avg`;
  const cadenceDeltaType = cadenceDiff === null ? 'neutral'
    : cadenceDiff > 5 ? 'up' : cadenceDiff < -5 ? 'down' : 'neutral';

  const clearanceDelta = clearance === null ? null
    : clearance < 10 ? 'low — possible shuffle'
    : clearance > 28 ? 'high — check form'
    : 'normal range';
  const clearanceDeltaType = clearance === null ? 'neutral'
    : clearance < 10 || clearance > 28 ? 'down' : 'neutral';

  const badgeLabel = scanning ? 'Scanning...' : connected ? 'Live' : 'No signal';

  return (
    <div className="app">
      <header className="app-header">
        <span className="app-title">SteadyStep</span>
        <div className="header-right">
          <div className={`live-badge${connected ? '' : ' live-badge--off'}`}>
            <div className="live-dot" />
            {badgeLabel}
          </div>
          {!connected && (
            <button className="scan-btn" onClick={handleScan} disabled={scanning}>
              {scanning ? 'Scanning...' : 'Scan'}
            </button>
          )}
        </div>
      </header>

      {!connected ? (
        <div className="no-device">
          {scanning
            ? <p className="no-device-text">Searching for SteadyStep-IMU...</p>
            : <p className="no-device-text">Device not found. Press Scan to connect.</p>
          }
        </div>
      ) : (
        <>
          <GaitCard
            classification={gait.classification}
            confidence={gait.confidence}
          />

          <div className="metrics-grid">
            <MetricCard
              label="Cadence"
              value={cadence !== null ? cadence : '--'}
              unit={cadence !== null ? 'spm' : undefined}
              delta={cadenceDelta}
              deltaType={cadenceDeltaType}
            />
            <MetricCard
              label="Total steps"
              value={steps !== null ? steps.toLocaleString() : '--'}
              delta={steps !== null ? 'this session' : null}
              deltaType="neutral"
            />
            <MetricCard
              label="Foot clearance"
              value={clearance !== null ? clearance.toFixed(1) : '--'}
              unit={clearance !== null ? 'cm' : undefined}
              delta={clearanceDelta}
              deltaType={clearanceDeltaType}
            />
            <MetricCard
              label="Gait similarity"
              value={similarity !== null ? similarity.toFixed(1) : '--'}
              unit={similarity !== null ? '/ 10' : undefined}
              deltaType="neutral"
            >
              {similarity !== null && (
                <div className="similarity-bar-bg">
                  <div
                    className="similarity-bar-fill"
                    style={{ width: `${(similarity / 10) * 100}%` }}
                  />
                </div>
              )}
            </MetricCard>
          </div>

          <CadenceTrend history={cadenceHistory.values} labels={cadenceHistory.labels} />
        </>
      )}
    </div>
  );
}
