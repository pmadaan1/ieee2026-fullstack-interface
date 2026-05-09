import { useEffect, useMemo, useState } from 'react';
import MetricCard from '../components/MetricCard';
import TimeSeriesChart from '../components/TimeSeriesChart';
import InsightsCard, { generateInsights } from '../components/InsightsCard';
import { fetchMinutes, isFirebaseEnabled, DEFAULT_UID } from '../firebase';

const RANGES = [
  { id: '1w', label: '1 week',    days: 7,   bucketHours: 6  },
  { id: '1m', label: '1 month',   days: 30,  bucketHours: 24 },
  { id: '6m', label: '6 months',  days: 180, bucketHours: 24 * 7 },
];

// ---------- bucket helpers ----------

function bucketize(rows, bucketHours) {
  // Group minute docs into time buckets, average numeric fields, sum
  // walking_minutes (assume each minute doc represents 1 minute of activity).
  const bucketMs = bucketHours * 60 * 60 * 1000;
  if (!rows.length) return [];

  const map = new Map();
  for (const r of rows) {
    const key = Math.floor(r.ts_ms / bucketMs) * bucketMs;
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(r);
  }

  const out = [];
  const keys = [...map.keys()].sort((a, b) => a - b);
  for (const key of keys) {
    const xs = map.get(key);
    const numeric = (field) => {
      const vs = xs.map(x => x[field]).filter(v => v != null && !isNaN(v));
      return vs.length ? vs.reduce((a, b) => a + b, 0) / vs.length : null;
    };
    out.push({
      ts: key,
      cadence:     numeric('cadence'),
      speed:       numeric('speed'),
      stride:      numeric('stride'),
      clearance:   numeric('clearance'),
      asymmetry:   numeric('asymmetry'),
      variability: numeric('variability'),
      stance_pct:  numeric('stance_pct'),
      stance_time: numeric('stance_time'),
      swing_time:  numeric('swing_time'),
      step_time:   numeric('step_time'),
      intensity:   numeric('intensity'),
      walking_minutes: xs.length,    // each minute doc ≈ 1 minute of activity
    });
  }
  return out;
}

function formatBucketLabel(ts, bucketHours) {
  const d = new Date(ts);
  if (bucketHours <= 24) return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function summaryAverages(buckets) {
  const out = {};
  const fields = ['cadence', 'speed', 'stride', 'clearance', 'asymmetry',
                  'variability', 'stance_pct', 'intensity', 'stance_time', 'swing_time'];
  for (const f of fields) {
    const xs = buckets.map(b => b[f]).filter(v => v != null);
    out[f] = xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
  }
  out.walking_minutes = buckets.reduce((s, b) => s + (b.walking_minutes ?? 0), 0);
  return out;
}

function trendDelta(curr, prev, fmt = (v) => v?.toFixed(1)) {
  if (curr == null || prev == null || prev === 0) return null;
  const diff = curr - prev;
  const pct = (diff / prev) * 100;
  if (Math.abs(pct) < 5) return { text: 'stable vs prev', type: 'neutral' };
  return {
    text: `${diff > 0 ? '+' : ''}${pct.toFixed(0)}% vs prev`,
    type: 'neutral', // semantic coloring deferred to caller
    diff,
    pct,
  };
}

// ---------- main view ----------

export default function LongTermView() {
  const [rangeId, setRangeId] = useState('1w');
  const [rows, setRows]       = useState(null);   // null = loading; [] = no data
  const [error, setError]     = useState(null);

  const range = useMemo(() => RANGES.find(r => r.id === rangeId), [rangeId]);
  const cutoffMs = useMemo(
    () => Date.now() - range.days * 24 * 60 * 60 * 1000,
    [range.days],
  );
  const prevCutoffMs = useMemo(
    () => Date.now() - 2 * range.days * 24 * 60 * 60 * 1000,
    [range.days],
  );

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setRows(null); setError(null);
      try {
        // Fetch the current period AND the preceding one (for trends).
        const all = await fetchMinutes(DEFAULT_UID, prevCutoffMs);
        if (cancelled) return;
        setRows(all);
      } catch (err) {
        console.error(err);
        if (!cancelled) { setError(err.message || 'Query failed'); setRows([]); }
      }
    }
    if (isFirebaseEnabled()) load();
    else { setRows([]); setError(null); }
    return () => { cancelled = true; };
  }, [prevCutoffMs]);

  const currRows = useMemo(() => (rows || []).filter(r => r.ts_ms >= cutoffMs), [rows, cutoffMs]);
  const prevRows = useMemo(() => (rows || []).filter(r => r.ts_ms < cutoffMs), [rows, cutoffMs]);

  const buckets     = useMemo(() => bucketize(currRows, range.bucketHours), [currRows, range.bucketHours]);
  const prevBuckets = useMemo(() => bucketize(prevRows, range.bucketHours), [prevRows, range.bucketHours]);

  const summary     = useMemo(() => summaryAverages(buckets), [buckets]);
  const prevSummary = useMemo(() => summaryAverages(prevBuckets), [prevBuckets]);

  const insights = useMemo(
    () => generateInsights(buckets, prevBuckets, `over the last ${range.label}`),
    [buckets, prevBuckets, range.label],
  );

  const labels = useMemo(() => buckets.map(b => formatBucketLabel(b.ts, range.bucketHours)), [buckets, range.bucketHours]);

  // ----- render -----
  return (
    <>
      <div className="lt-controls">
        {RANGES.map(r => (
          <button key={r.id}
                  className={`lt-range-btn${r.id === rangeId ? ' lt-range-btn--active' : ''}`}
                  onClick={() => setRangeId(r.id)}>
            {r.label}
          </button>
        ))}
      </div>

      {!isFirebaseEnabled() && (
        <div className="lt-empty">
          <strong>Firebase isn't configured yet.</strong>
          <span>Add your project credentials to <code>frontend/.env.local</code> and the backend's
                <code>firebase-credentials.json</code>, then restart both servers.
                See <code>frontend/.env.local.example</code> for the variable names.</span>
        </div>
      )}

      {isFirebaseEnabled() && error && (
        <div className="lt-empty lt-empty--error">
          <strong>Couldn't load data.</strong>
          <span>{error}</span>
        </div>
      )}

      {isFirebaseEnabled() && !error && rows === null && (
        <div className="lt-empty"><span>Loading {range.label} of data…</span></div>
      )}

      {isFirebaseEnabled() && !error && rows !== null && currRows.length === 0 && (
        <div className="lt-empty">
          <strong>No data for the selected range.</strong>
          <span>Open the Live tab, connect your IMU, and walk for a minute. Data starts flowing into Firestore once a minute aggregates.</span>
        </div>
      )}

      {currRows.length > 0 && (
        <>
          <InsightsCard insights={insights} />

          <div className="section-label">Period averages</div>
          <div className="metrics-grid metrics-grid--3">
            <MetricCard label="Walking speed"
              value={summary.speed != null ? summary.speed.toFixed(2) : '--'}
              unit={summary.speed != null ? 'm/s' : undefined}
              delta={trendDelta(summary.speed, prevSummary.speed)?.text}
              deltaType="neutral"
              accent="primary" />
            <MetricCard label="Cadence"
              value={summary.cadence != null ? summary.cadence.toFixed(0) : '--'}
              unit={summary.cadence != null ? 'spm' : undefined}
              delta={trendDelta(summary.cadence, prevSummary.cadence)?.text}
              deltaType="neutral" />
            <MetricCard label="Active time"
              value={summary.walking_minutes ? Math.round(summary.walking_minutes) : '--'}
              unit={summary.walking_minutes ? 'min' : undefined}
              delta={trendDelta(summary.walking_minutes, prevSummary.walking_minutes)?.text}
              deltaType="neutral" />
          </div>

          <div className="section-label">Stride mechanics</div>
          <div className="metrics-grid metrics-grid--4">
            <MetricCard label="Stride length"
              value={summary.stride != null ? summary.stride.toFixed(2) : '--'}
              unit={summary.stride != null ? 'm' : undefined}
              delta={trendDelta(summary.stride, prevSummary.stride)?.text}
              deltaType="neutral" />
            <MetricCard label="Step asymmetry"
              value={summary.asymmetry != null ? summary.asymmetry.toFixed(1) : '--'}
              unit={summary.asymmetry != null ? '%' : undefined}
              delta={trendDelta(summary.asymmetry, prevSummary.asymmetry)?.text}
              deltaType="neutral" />
            <MetricCard label="Stride variability"
              value={summary.variability != null ? summary.variability.toFixed(1) : '--'}
              unit={summary.variability != null ? '%' : undefined}
              delta={trendDelta(summary.variability, prevSummary.variability)?.text}
              deltaType="neutral" />
            <MetricCard label="Foot clearance"
              value={summary.clearance != null ? summary.clearance.toFixed(1) : '--'}
              unit={summary.clearance != null ? 'cm' : undefined}
              delta={trendDelta(summary.clearance, prevSummary.clearance)?.text}
              deltaType="neutral" />
          </div>

          <div className="section-label">Trends over {range.label}</div>
          <TimeSeriesChart
            title="Walking speed" range={range.label} unit="m/s"
            labels={labels} values={buckets.map(b => b.speed)}
            color="#1668C1" yMin={0} yMax={2.0}
            targetMin={1.2} targetMax={1.8}
          />
          <TimeSeriesChart
            title="Cadence" range={range.label} unit="spm"
            labels={labels} values={buckets.map(b => b.cadence)}
            color="#2A82DA" yMin={60} yMax={150}
            targetMin={100} targetMax={120}
          />
          <TimeSeriesChart
            title="Step asymmetry" range={range.label} unit="%"
            labels={labels} values={buckets.map(b => b.asymmetry)}
            color="#C97E1A" yMin={0} yMax={30}
          />
          <TimeSeriesChart
            title="Stride variability" range={range.label} unit="%"
            labels={labels} values={buckets.map(b => b.variability)}
            color="#9F571B" yMin={0} yMax={25}
          />
          <TimeSeriesChart
            title="Foot clearance" range={range.label} unit="cm"
            labels={labels} values={buckets.map(b => b.clearance)}
            color="#0FA672" yMin={0} yMax={30}
          />
          <TimeSeriesChart
            title="Active minutes per bucket" range={range.label} unit="min"
            labels={labels} values={buckets.map(b => b.walking_minutes)}
            color="#4FA0EE" yMin={0}
          />
        </>
      )}
    </>
  );
}
