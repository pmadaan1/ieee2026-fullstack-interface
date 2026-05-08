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

export default function App() {
  const [connected, setConnected]     = useState(false);
  const [scanning, setScanning]       = useState(false);
  const [raw, setRaw]                 = useState(null);
  const [cadence, setCadence]         = useState(null);
  const [steps, setSteps]             = useState(null);
  const [clearance, setClearance]     = useState(null);
  const [similarity, setSimilarity]   = useState(null);
  const [gait, setGait]               = useState({ classification: 'Normal', confidence: null });
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
