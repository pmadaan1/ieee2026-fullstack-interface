import { useState, useEffect, useRef, useCallback } from 'react';
import GaitCard from '../components/GaitCard';
import MetricCard from '../components/MetricCard';
import CadenceTrend from '../components/CadenceTrend';

const MAX_POINTS    = 20;                          // 20 ticks * 0.5s = 10s graph
const WS_URL = process.env.REACT_APP_WS_URL || 'ws://localhost:8000/ws';
const SERVICE_UUID  = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
const CHAR_UUID     = '6e400003-b5a3-f393-e0a9-e50e24dcca9e';
const CALIBRATION_S = 30;
const BASELINE_KEY  = 'steadystep_baseline';

const BASELINE_FIELDS = [
  'cadence', 'speed', 'stride', 'clearance', 'asymmetry', 'variability',
  'step_time', 'stance_time', 'swing_time', 'stance_pct', 'intensity',
];

function formatTime(date) {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
function titleCase(s) { if (!s) return '--'; return s.charAt(0).toUpperCase() + s.slice(1); }

// ---------- contextual range deltas ----------
function speedRange(v) {
  if (v >= 1.2) return { text: 'Healthy adult range', type: 'up' };
  if (v >= 1.0) return { text: 'Moderate', type: 'neutral' };
  if (v >= 0.6) return { text: 'Reduced — monitor', type: 'down' };
  return { text: 'Significant limitation', type: 'down' };
}
function cadenceRange(v) {
  if (v >= 100 && v <= 120) return { text: 'Normal walking', type: 'up' };
  if (v > 140) return { text: 'Running pace', type: 'neutral' };
  if (v < 80) return { text: 'Slow', type: 'down' };
  return { text: 'Brisk / slow', type: 'neutral' };
}
function asymmetryRange(v) {
  if (v < 5)  return { text: 'Symmetric', type: 'up' };
  if (v < 15) return { text: 'Mild asymmetry', type: 'neutral' };
  return { text: 'Notable — investigate', type: 'down' };
}
function variabilityRange(v) {
  if (v < 3)  return { text: 'Consistent', type: 'up' };
  if (v < 12) return { text: 'Moderate', type: 'neutral' };
  return { text: 'High — fall risk', type: 'down' };
}
function clearanceRange(v) {
  if (v >= 15) return { text: 'Good lift', type: 'up' };
  if (v >= 5)  return { text: 'Adequate', type: 'neutral' };
  return { text: 'Low — trip risk', type: 'down' };
}
function strideRange(v) {
  if (v >= 1.2) return { text: 'Long stride', type: 'up' };
  if (v >= 0.6) return { text: 'Typical', type: 'neutral' };
  return { text: 'Short', type: 'down' };
}
function stanceRange(v) {
  if (v >= 55 && v <= 65) return { text: 'Typical 55–65%', type: 'up' };
  if (v > 65) return { text: 'Long stance — instability?', type: 'down' };
  return { text: 'Short stance', type: 'neutral' };
}

function baselineDelta(field, current, baseline, opts = {}) {
  if (current == null || baseline == null) return null;
  const diff = current - baseline;
  const fmt = opts.unit ? `${diff > 0 ? '+' : ''}${diff.toFixed(opts.decimals ?? 2)} ${opts.unit}`
                        : `${diff > 0 ? '+' : ''}${diff.toFixed(opts.decimals ?? 1)}`;
  const text = `${fmt} vs baseline`;
  const tol = baseline * (opts.tolerance ?? 0.05);
  if (Math.abs(diff) <= tol) return { text: 'at baseline', type: 'neutral' };
  if (opts.worseUp)   return { text, type: diff > 0 ? 'down' : 'up' };
  if (opts.worseDown) return { text, type: diff > 0 ? 'up' : 'down' };
  return { text, type: 'neutral' };
}


export default function LiveView() {
  const [connected, setConnected]     = useState(false);
  const [scanning, setScanning]       = useState(false);
  const [raw, setRaw]                 = useState(null);
  const [metrics, setMetrics]         = useState(null);
  const [cadenceHistory, setCadenceHistory] = useState({ values: [], labels: [] });

  const [calibrating, setCalibrating]         = useState(false);
  const [calibrationLeft, setCalibrationLeft] = useState(CALIBRATION_S);
  const [baseline, setBaseline] = useState(() => {
    try { const s = localStorage.getItem(BASELINE_KEY); return s ? JSON.parse(s) : null; }
    catch { return null; }
  });

  const wsRef         = useRef(null);
  const deviceRef     = useRef(null);
  const charRef       = useRef(null);
  const calibBufRef   = useRef([]);
  const calibTimerRef = useRef(null);

  useEffect(() => {
    let ws; let reconnectTimeout;
    function connect() {
      ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      ws.onmessage = (event) => {
        const { metrics: m } = JSON.parse(event.data);
        if (!m) return;
        setMetrics(m);
        if (calibTimerRef.current) calibBufRef.current.push(m);
        if (m.cadence !== null && m.cadence !== undefined) {
          setCadenceHistory(prev => ({
            values: [...prev.values.slice(-(MAX_POINTS - 1)), m.cadence],
            labels: [...prev.labels.slice(-(MAX_POINTS - 1)), formatTime(new Date())],
          }));
        }
      };
      ws.onclose = () => { reconnectTimeout = setTimeout(connect, 3000); };
      ws.onerror = () => ws.close();
    }
    connect();
    return () => { clearTimeout(reconnectTimeout); ws?.close(); };
  }, []);

  const handleIMUData = useCallback((event) => {
    const text  = new TextDecoder().decode(event.target.value).trim();
    const parts = text.split(',');
    if (parts.length < 7) return;
    const rawData = {
      esp32_ms: parseInt(parts[0]),
      ax: parseFloat(parts[1]), ay: parseFloat(parts[2]), az: parseFloat(parts[3]),
      gx: parseFloat(parts[4]), gy: parseFloat(parts[5]), gz: parseFloat(parts[6]),
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
        setConnected(false); setRaw(null); setMetrics(null);
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
    if (deviceRef.current?.gatt?.connected) deviceRef.current.gatt.disconnect();
    deviceRef.current = null;
    setConnected(false); setRaw(null); setMetrics(null);
    cancelCalibration();
  }

  function startCalibration() {
    calibBufRef.current = [];
    setCalibrationLeft(CALIBRATION_S);
    setCalibrating(true);
    const startMs = Date.now();
    calibTimerRef.current = setInterval(() => {
      const elapsed = (Date.now() - startMs) / 1000;
      const left = Math.max(0, CALIBRATION_S - elapsed);
      setCalibrationLeft(left);
      if (elapsed >= CALIBRATION_S) finishCalibration();
    }, 100);
  }

  function cancelCalibration() {
    if (calibTimerRef.current) { clearInterval(calibTimerRef.current); calibTimerRef.current = null; }
    setCalibrating(false);
    setCalibrationLeft(CALIBRATION_S);
    calibBufRef.current = [];
  }

  function finishCalibration() {
    if (calibTimerRef.current) { clearInterval(calibTimerRef.current); calibTimerRef.current = null; }
    setCalibrating(false);
    const samples = calibBufRef.current; calibBufRef.current = [];
    const newBaseline = { capturedAt: Date.now(), sampleCount: samples.length };
    BASELINE_FIELDS.forEach(field => {
      const vals = samples.map(s => s[field]).filter(v => v !== null && v !== undefined);
      newBaseline[field] = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    });
    setBaseline(newBaseline);
    try { localStorage.setItem(BASELINE_KEY, JSON.stringify(newBaseline)); } catch {}
  }

  function resetBaseline() {
    setBaseline(null);
    try { localStorage.removeItem(BASELINE_KEY); } catch {}
  }

  const m = metrics || {};
  const has = (v) => v !== null && v !== undefined;
  const isIdle = m.state === 'idle';

  // Prefer the new activity model (Walking/Turning/Stairs/Sitting/Standing/Idle)
  // over the legacy LGBM state — it's more granular. Fall back to the
  // legacy state if the new field isn't populated yet (first ~10s after
  // connecting, before the buffer fills).
  const activityLabel = m.activity || titleCase(m.state) || '--';
  const activityDelta = has(m.activity_confidence)
    ? `${m.activity_confidence}% confident`
    : (has(m.state_confidence) ? `${m.state_confidence}% confident` : null);
  const speedKmh = has(m.speed) ? (m.speed * 3.6) : null;

  // Parkinson's indicator. Model is advisory, not diagnostic. The label
  // flips to "Atypical" only at high confidence (P(parkinsons) ≥ 0.90,
  // applied in the backend). The percentage is the underlying PD likelihood
  // in either case — useful even when the label stays "Typical".
  const pdLabel = isIdle ? '--'
    : m.parkinsons === 'parkinsons' ? 'Atypical'
    : m.parkinsons === 'control'    ? 'Typical'
    : '--';
  const pdDelta = isIdle ? null
    : has(m.parkinsons_confidence)
      ? `${m.parkinsons_confidence}% PD likelihood`
      : null;
  const pdDeltaType = isIdle || !has(m.parkinsons_confidence) ? 'neutral'
    : m.parkinsons === 'parkinsons' ? 'down' : 'neutral';

  function deltaFor(field, current, rangeFn, opts = {}) {
    if (current == null || isIdle) return null;
    if (baseline && baseline[field] != null) return baselineDelta(field, current, baseline[field], opts);
    return rangeFn ? rangeFn(current) : null;
  }

  const dCadence    = deltaFor('cadence',     m.cadence,     cadenceRange,     { decimals: 0 });
  const dSpeed      = deltaFor('speed',       m.speed,       speedRange,       { decimals: 2, unit: 'm/s', worseDown: true });
  const dStride     = deltaFor('stride',      m.stride,      strideRange,      { decimals: 2, unit: 'm', worseDown: true });
  const dAsymmetry  = deltaFor('asymmetry',   m.asymmetry,   asymmetryRange,   { decimals: 1, unit: '%', worseUp: true });
  const dVariability = deltaFor('variability', m.variability, variabilityRange, { decimals: 1, unit: '%', worseUp: true });
  const dClearance  = deltaFor('clearance',   m.clearance,   clearanceRange,   { decimals: 1, unit: 'cm', worseDown: true });
  const dStancePct  = deltaFor('stance_pct',  m.stance_pct,  stanceRange,      { decimals: 1, unit: '%' });
  const dStanceTime = deltaFor('stance_time', m.stance_time, null,             { decimals: 2, unit: 's' });
  const dSwingTime  = deltaFor('swing_time',  m.swing_time,  null,             { decimals: 2, unit: 's' });
  const dIntensity  = deltaFor('intensity',   m.intensity,   null,             { decimals: 2, unit: 'm/s²' });

  const idleStr = isIdle ? 'stationary' : null;
  const badgeLabel = scanning ? 'Scanning...' : connected ? 'Live' : 'No signal';
  const calibPct = ((CALIBRATION_S - calibrationLeft) / CALIBRATION_S) * 100;

  return (
    <>
      <div className="live-controls">
        <div className={`live-badge${connected ? '' : ' live-badge--off'}`}>
          <div className="live-dot" />{badgeLabel}
        </div>
        {connected
          ? <button className="disconnect-btn" onClick={handleDisconnect}>Disconnect</button>
          : <button className="scan-btn" onClick={handleScan} disabled={scanning}>
              {scanning ? 'Scanning...' : 'Scan'}
            </button>
        }
      </div>

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
            classification={m.classification || 'Stationary'}
            confidence={has(m.confidence) ? m.confidence : null}
          />

          <div className="calib-card">
            {calibrating ? (
              <>
                <div className="calib-text">
                  <strong>Calibrating baseline</strong>
                  <span className="calib-sub">walk normally — {Math.ceil(calibrationLeft)}s left</span>
                </div>
                <div className="calib-progress">
                  <div className="calib-progress-fill" style={{ width: `${calibPct}%` }} />
                </div>
                <button className="calib-btn calib-btn--ghost" onClick={cancelCalibration}>Cancel</button>
              </>
            ) : baseline ? (
              <>
                <div className="calib-text">
                  <strong>Baseline active</strong>
                  <span className="calib-sub">
                    {baseline.cadence?.toFixed(0)} spm · {baseline.speed?.toFixed(2)} m/s · {baseline.stride?.toFixed(2)} m stride
                  </span>
                </div>
                <button className="calib-btn calib-btn--ghost" onClick={resetBaseline}>Reset</button>
                <button className="calib-btn" onClick={startCalibration}>Recalibrate</button>
              </>
            ) : (
              <>
                <div className="calib-text">
                  <strong>Set personal baseline</strong>
                  <span className="calib-sub">Walk for 30s — get personalized deltas on every metric</span>
                </div>
                <button className="calib-btn" onClick={startCalibration}>Calibrate (30s)</button>
              </>
            )}
          </div>

          <div className="section-label">Live activity</div>
          <div className="metrics-grid metrics-grid--3">
            <MetricCard label="Activity" value={activityLabel} delta={activityDelta}
                        deltaType="neutral" accent="primary" />
            <MetricCard label="Walking speed"
              value={has(m.speed) ? m.speed.toFixed(2) : '--'}
              unit={has(m.speed) ? 'm/s' : undefined}
              delta={isIdle ? idleStr : (dSpeed?.text ?? (speedKmh != null ? `${speedKmh.toFixed(1)} km/h` : null))}
              deltaType={dSpeed?.type ?? 'neutral'} />
            <MetricCard label="Cadence"
              value={has(m.cadence) ? m.cadence : '--'}
              unit={has(m.cadence) ? 'spm' : undefined}
              delta={isIdle ? idleStr : dCadence?.text}
              deltaType={dCadence?.type ?? 'neutral'} />
          </div>

          <div className="section-label">Movement signature</div>
          <div className="metrics-grid metrics-grid--2">
            <MetricCard label="Parkinson's indicator (advisory)"
              value={pdLabel}
              delta={pdDelta}
              deltaType={pdDeltaType} />
            <MetricCard label="Activity breakdown"
              value={
                m.activity_distribution
                  ? Object.entries(m.activity_distribution)
                      .filter(([, v]) => v >= 5)
                      .sort((a, b) => b[1] - a[1])
                      .slice(0, 1)
                      .map(([k]) => k)[0] ?? '--'
                  : '--'
              }
              delta={
                m.activity_distribution
                  ? Object.entries(m.activity_distribution)
                      .filter(([, v]) => v >= 5)
                      .sort((a, b) => b[1] - a[1])
                      .slice(0, 3)
                      .map(([k, v]) => `${k} ${v.toFixed(0)}%`)
                      .join(' · ')
                  : null
              }
              deltaType="neutral" />
          </div>

          <div className="section-label">Stride mechanics</div>
          <div className="metrics-grid metrics-grid--4">
            <MetricCard label="Stride length"
              value={has(m.stride) ? m.stride.toFixed(2) : '--'}
              unit={has(m.stride) ? 'm' : undefined}
              delta={isIdle ? idleStr : dStride?.text}
              deltaType={dStride?.type ?? 'neutral'} />
            <MetricCard label="Step asymmetry"
              value={has(m.asymmetry) ? m.asymmetry.toFixed(1) : '--'}
              unit={has(m.asymmetry) ? '%' : undefined}
              delta={isIdle ? null : dAsymmetry?.text}
              deltaType={dAsymmetry?.type ?? 'neutral'} />
            <MetricCard label="Stride variability"
              value={has(m.variability) ? m.variability.toFixed(1) : '--'}
              unit={has(m.variability) ? '%' : undefined}
              delta={isIdle ? null : dVariability?.text}
              deltaType={dVariability?.type ?? 'neutral'} />
            <MetricCard label="Steps (window)"
              value={has(m.steps) ? m.steps.toLocaleString() : '--'}
              delta={has(m.steps) ? 'last 10 s' : null}
              deltaType="neutral" />
          </div>

          <div className="section-label">Foot mechanics</div>
          <div className="metrics-grid metrics-grid--4">
            <MetricCard label="Foot clearance"
              value={has(m.clearance) ? m.clearance.toFixed(1) : '--'}
              unit={has(m.clearance) ? 'cm' : undefined}
              delta={isIdle ? null : dClearance?.text}
              deltaType={dClearance?.type ?? 'neutral'} >
              {has(m.clearance) && (
                <div className="similarity-bar-bg">
                  <div className="similarity-bar-fill"
                       style={{ width: `${Math.min(100, (m.clearance / 30) * 100)}%` }} />
                </div>
              )}
            </MetricCard>
            <MetricCard label="Stance phase"
              value={has(m.stance_pct) ? m.stance_pct.toFixed(0) : '--'}
              unit={has(m.stance_pct) ? '%' : undefined}
              delta={isIdle ? 'planted' : dStancePct?.text}
              deltaType={dStancePct?.type ?? 'neutral'} />
            <MetricCard label="Stance time"
              value={has(m.stance_time) ? m.stance_time.toFixed(2) : '--'}
              unit={has(m.stance_time) ? 's' : undefined}
              delta={isIdle ? null : dStanceTime?.text}
              deltaType={dStanceTime?.type ?? 'neutral'} />
            <MetricCard label="Swing time"
              value={has(m.swing_time) ? m.swing_time.toFixed(2) : '--'}
              unit={has(m.swing_time) ? 's' : undefined}
              delta={isIdle ? null : dSwingTime?.text}
              deltaType={dSwingTime?.type ?? 'neutral'} />
          </div>

          <div className="section-label">Effort</div>
          <div className="metrics-grid metrics-grid--2">
            <MetricCard label="Movement intensity"
              value={has(m.intensity) ? m.intensity.toFixed(2) : '--'}
              unit={has(m.intensity) ? 'm/s²' : undefined}
              delta={
                isIdle ? 'idle' :
                m.intensity != null && m.intensity > 6 ? 'high — vigorous' :
                m.intensity != null && m.intensity < 1 ? 'low' : 'moderate'
              }
              deltaType={dIntensity?.type ?? 'neutral'} />
            <MetricCard label="Step time"
              value={has(m.step_time) ? m.step_time.toFixed(2) : '--'}
              unit={has(m.step_time) ? 's' : undefined}
              delta={isIdle ? null : (m.step_time != null ? `${(60 / m.step_time).toFixed(0)} spm equivalent` : null)}
              deltaType="neutral" />
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
    </>
  );
}
