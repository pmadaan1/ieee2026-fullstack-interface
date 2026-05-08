import { useState, useEffect, useRef, useCallback } from 'react';
import GaitCard from './components/GaitCard';
import MetricCard from './components/MetricCard';
import CadenceTrend from './components/CadenceTrend';
import './App.css';

const MAX_POINTS   = 20;
const WS_URL       = 'ws://localhost:8000/ws';
const SERVICE_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
const CHAR_UUID    = '6e400003-b5a3-f393-e0a9-e50e24dcca9e';

function formatTime(date) {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function titleCase(s) {
  if (!s) return '--';
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export default function App() {
  const [connected, setConnected]     = useState(false);
  const [scanning, setScanning]       = useState(false);
  const [raw, setRaw]                 = useState(null);
  const [metrics, setMetrics]         = useState(null);
  const [cadenceHistory, setCadenceHistory] = useState({ values: [], labels: [] });

  const wsRef     = useRef(null);
  const deviceRef = useRef(null);
  const charRef   = useRef(null);

  // WebSocket — stays open always, receives processed metrics from backend
  useEffect(() => {
    let ws;
    let reconnectTimeout;

    function connect() {
      ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        const { metrics: m } = JSON.parse(event.data);
        if (!m) return;

        setMetrics(m);

        if (m.cadence !== null && m.cadence !== undefined) {
          setCadenceHistory(prev => ({
            values: [...prev.values.slice(-(MAX_POINTS - 1)), m.cadence],
            labels: [...prev.labels.slice(-(MAX_POINTS - 1)), formatTime(new Date())],
          }));
        }
      };

      ws.onclose = () => {
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

  // Called on each BLE notification — parses bytes and forwards raw frame to backend
  const handleIMUData = useCallback((event) => {
    const text  = new TextDecoder().decode(event.target.value).trim();
    const parts = text.split(',');
    if (parts.length < 7) return;

    const rawData = {
      esp32_ms: parseInt(parts[0]),
      ax: parseFloat(parts[1]),
      ay: parseFloat(parts[2]),
      az: parseFloat(parts[3]),
      gx: parseFloat(parts[4]),
      gy: parseFloat(parts[5]),
      gz: parseFloat(parts[6]),
    };

    setRaw(rawData);

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ raw: rawData }));
    }
  }, []);

  async function handleScan() {
    setScanning(true);
    try {
      const device = await navigator.bluetooth.requestDevice({
        filters: [{ name: 'SteadyStep-IMU' }],
        optionalServices: [SERVICE_UUID],
      });
      deviceRef.current = device;

      device.addEventListener('gattserverdisconnected', () => {
        setConnected(false);
        setRaw(null);
        setMetrics(null);
      });

      const server  = await device.gatt.connect();
      const service = await server.getPrimaryService(SERVICE_UUID);
      const char    = await service.getCharacteristic(CHAR_UUID);
      charRef.current = char;

      await char.startNotifications();
      char.addEventListener('characteristicvaluechanged', handleIMUData);

      setConnected(true);
    } catch (err) {
      if (err.name !== 'NotFoundError') console.error('BLE error:', err);
    } finally {
      setScanning(false);
    }
  }

  async function handleDisconnect() {
    if (charRef.current) {
      charRef.current.removeEventListener('characteristicvaluechanged', handleIMUData);
      await charRef.current.stopNotifications().catch(() => {});
      charRef.current = null;
    }
    if (deviceRef.current?.gatt?.connected) {
      deviceRef.current.gatt.disconnect();
    }
    deviceRef.current = null;
    setConnected(false);
    setRaw(null);
    setMetrics(null);
  }

  // -- derived display values ----------------------------------------------
  const m = metrics || {};
  const has = (v) => v !== null && v !== undefined;

  const avgCadence = cadenceHistory.values.length
    ? Math.round(cadenceHistory.values.reduce((s, v) => s + v, 0) / cadenceHistory.values.length)
    : null;

  const cadenceDiff = has(m.cadence) && avgCadence !== null ? m.cadence - avgCadence : null;
  const cadenceDelta = cadenceDiff === null ? null
    : Math.abs(cadenceDiff) < 1 ? 'at average'
    : `${cadenceDiff > 0 ? '+' : ''}${cadenceDiff.toFixed(0)} from avg`;
  const cadenceDeltaType = cadenceDiff === null ? 'neutral'
    : cadenceDiff > 5 ? 'up' : cadenceDiff < -5 ? 'down' : 'neutral';

  const clearanceDelta = !has(m.clearance) ? null
    : m.clearance < 5 ? 'low — possible shuffle'
    : m.clearance > 28 ? 'high — check form'
    : 'normal range';
  const clearanceDeltaType = !has(m.clearance) ? 'neutral'
    : m.clearance < 5 || m.clearance > 28 ? 'down' : 'neutral';

  const speedKmh = has(m.speed) ? (m.speed * 3.6) : null;
  const speedDelta = speedKmh === null ? null : `${speedKmh.toFixed(1)} km/h`;

  const stanceDelta = !has(m.stance_pct) ? null
    : m.stance_pct > 70 ? 'mostly planted'
    : m.stance_pct < 20 ? 'mostly swinging'
    : 'balanced';

  const intensityDelta = !has(m.intensity) ? null
    : m.intensity < 0.5 ? 'low — idle'
    : m.intensity > 6 ? 'high — vigorous'
    : 'moderate';

  const stateLabel = titleCase(m.state);
  const stateDelta = has(m.state_confidence) ? `${m.state_confidence}% confident` : null;

  const badgeLabel = scanning ? 'Scanning...' : connected ? 'Live' : 'No signal';

  // -- render ---------------------------------------------------------------
  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="20" height="20">
              <path d="M4 19 L9 12 L13 16 L20 6" stroke="currentColor" strokeWidth="2.4"
                    fill="none" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="20" cy="6" r="2" fill="currentColor" />
            </svg>
          </div>
          <span className="app-title">SteadyStep</span>
        </div>
        <div className="header-right">
          <div className={`live-badge${connected ? '' : ' live-badge--off'}`}>
            <div className="live-dot" />
            {badgeLabel}
          </div>
          {connected
            ? <button className="disconnect-btn" onClick={handleDisconnect}>Disconnect</button>
            : <button className="scan-btn" onClick={handleScan} disabled={scanning}>
                {scanning ? 'Scanning...' : 'Scan'}
              </button>
          }
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
            classification={m.classification || 'Normal'}
            confidence={has(m.confidence) ? m.confidence : null}
          />

          <div className="section-label">Live metrics</div>

          <div className="metrics-grid">
            <MetricCard
              label="Activity"
              value={stateLabel}
              delta={stateDelta}
              deltaType="neutral"
              accent="primary"
            />
            <MetricCard
              label="Cadence"
              value={has(m.cadence) ? m.cadence : '--'}
              unit={has(m.cadence) ? 'spm' : undefined}
              delta={cadenceDelta}
              deltaType={cadenceDeltaType}
            />
            <MetricCard
              label="Walking speed"
              value={has(m.speed) ? m.speed.toFixed(2) : '--'}
              unit={has(m.speed) ? 'm/s' : undefined}
              delta={speedDelta}
              deltaType="neutral"
            />
            <MetricCard
              label="Steps (window)"
              value={has(m.steps) ? m.steps.toLocaleString() : '--'}
              delta={has(m.steps) ? 'last 10 s' : null}
              deltaType="neutral"
            />
            <MetricCard
              label="Stride length"
              value={has(m.stride) ? m.stride.toFixed(2) : '--'}
              unit={has(m.stride) ? 'm' : undefined}
              deltaType="neutral"
            />
            <MetricCard
              label="Foot clearance"
              value={has(m.clearance) ? m.clearance.toFixed(1) : '--'}
              unit={has(m.clearance) ? 'cm' : undefined}
              delta={clearanceDelta}
              deltaType={clearanceDeltaType}
            />
            <MetricCard
              label="Gait similarity"
              value={has(m.similarity) ? m.similarity.toFixed(1) : '--'}
              unit={has(m.similarity) ? '/ 10' : undefined}
              deltaType="neutral"
            >
              {has(m.similarity) && (
                <div className="similarity-bar-bg">
                  <div
                    className="similarity-bar-fill"
                    style={{ width: `${(m.similarity / 10) * 100}%` }}
                  />
                </div>
              )}
            </MetricCard>
            <MetricCard
              label="Stance phase"
              value={has(m.stance_pct) ? m.stance_pct.toFixed(0) : '--'}
              unit={has(m.stance_pct) ? '%' : undefined}
              delta={stanceDelta}
              deltaType="neutral"
            />
            <MetricCard
              label="Movement intensity"
              value={has(m.intensity) ? m.intensity.toFixed(2) : '--'}
              unit={has(m.intensity) ? 'm/s²' : undefined}
              delta={intensityDelta}
              deltaType="neutral"
            />
          </div>

          <CadenceTrend history={cadenceHistory.values} labels={cadenceHistory.labels} />

          {raw && (
            <div className="raw-card">
              <div className="raw-title">Raw IMU data</div>
              <div className="raw-groups">
                <div className="raw-group">
                  <div className="raw-group-label">Accelerometer (m/s²)</div>
                  <div className="raw-row"><span>ax</span><span>{raw.ax.toFixed(2)}</span></div>
                  <div className="raw-row"><span>ay</span><span>{raw.ay.toFixed(2)}</span></div>
                  <div className="raw-row"><span>az</span><span>{raw.az.toFixed(2)}</span></div>
                </div>
                <div className="raw-group">
                  <div className="raw-group-label">Gyroscope (°/s)</div>
                  <div className="raw-row"><span>gx</span><span>{raw.gx.toFixed(2)}</span></div>
                  <div className="raw-row"><span>gy</span><span>{raw.gy.toFixed(2)}</span></div>
                  <div className="raw-row"><span>gz</span><span>{raw.gz.toFixed(2)}</span></div>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
