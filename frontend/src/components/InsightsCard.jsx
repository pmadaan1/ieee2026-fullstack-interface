// Rule-based health insights generated from aggregated long-term metrics.
// Designed to be positive, neutral, or concerning — coloring follows MetricCard.

const SEVERITY = {
  positive: { color: '#0E7A53', bg: '#E1F1EA', dot: '#0FA672' },
  neutral:  { color: '#1E3A5F', bg: '#EEF5FC', dot: '#2A82DA' },
  concern:  { color: '#9F571B', bg: '#FFEAD2', dot: '#C97E1A' },
  alert:    { color: '#A1431F', bg: '#FFE2D5', dot: '#D04F2A' },
};

export function generateInsights(buckets, prevBuckets, rangeLabel) {
  // buckets: array of { ts, cadence, speed, stride, asymmetry, variability,
  //                     clearance, stance_pct, walking_minutes, ... }
  // prevBuckets: same shape, for the preceding period (for trend deltas)
  const out = [];
  if (!buckets || !buckets.length) return out;

  const avg = (key) => {
    const xs = buckets.map(b => b[key]).filter(v => v != null && !isNaN(v));
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
  };
  const prevAvg = (key) => {
    if (!prevBuckets?.length) return null;
    const xs = prevBuckets.map(b => b[key]).filter(v => v != null && !isNaN(v));
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
  };

  const speed       = avg('speed');
  const cadence     = avg('cadence');
  const asymmetry   = avg('asymmetry');
  const variability = avg('variability');
  const clearance   = avg('clearance');
  const totalMin    = buckets.reduce((s, b) => s + (b.walking_minutes ?? 0), 0);
  const prevTotalMin = prevBuckets?.reduce((s, b) => s + (b.walking_minutes ?? 0), 0) ?? null;

  // 1. Walking speed — the headline.
  if (speed != null) {
    if (speed >= 1.2) {
      out.push({
        severity: 'positive',
        title: 'Walking speed is in a healthy range',
        body: `Average ${speed.toFixed(2)} m/s ${rangeLabel}. Above 1.2 m/s is the typical healthy adult range and correlates with strong overall mobility.`,
      });
    } else if (speed >= 0.6) {
      out.push({
        severity: 'concern',
        title: 'Walking speed is below the typical range',
        body: `Average ${speed.toFixed(2)} m/s ${rangeLabel}. Consistently under 1.0 m/s in older adults is associated with a higher risk of mobility decline.`,
      });
    } else {
      out.push({
        severity: 'alert',
        title: 'Walking speed indicates significant limitation',
        body: `Average ${speed.toFixed(2)} m/s ${rangeLabel}. Speeds below 0.6 m/s warrant clinical follow-up.`,
      });
    }

    const ps = prevAvg('speed');
    if (ps != null && Math.abs(speed - ps) / ps > 0.1) {
      const dir = speed > ps ? 'increased' : 'decreased';
      const pct = Math.abs((speed - ps) / ps * 100).toFixed(0);
      out.push({
        severity: speed > ps ? 'positive' : 'concern',
        title: `Walking speed ${dir} ${pct}% vs the previous period`,
        body: `From ${ps.toFixed(2)} → ${speed.toFixed(2)} m/s. Speed changes >10% are worth paying attention to.`,
      });
    }
  }

  // 2. Variability / fall risk.
  if (variability != null) {
    if (variability < 3) {
      out.push({
        severity: 'positive',
        title: 'Stride rhythm is highly consistent',
        body: `Stride variability averaged ${variability.toFixed(1)}% — well within the healthy range. Low variability is associated with strong balance and low fall risk.`,
      });
    } else if (variability >= 12) {
      out.push({
        severity: 'alert',
        title: 'Stride variability is elevated — possible fall risk',
        body: `Variability averaged ${variability.toFixed(1)}% ${rangeLabel}. Sustained variability above 12% is one of the more reliable predictors of falls.`,
      });
    }
  }

  // 3. Asymmetry.
  if (asymmetry != null && asymmetry >= 15) {
    out.push({
      severity: 'concern',
      title: 'Step asymmetry is notable',
      body: `Average ${asymmetry.toFixed(1)}% asymmetry ${rangeLabel}. Persistent asymmetry often indicates injury, weakness, or compensation on one side.`,
    });
  }

  // 4. Foot clearance.
  if (clearance != null && clearance < 5) {
    out.push({
      severity: 'concern',
      title: 'Foot clearance is low',
      body: `Average ${clearance.toFixed(1)} cm ${rangeLabel}. Low clearance is one of the strongest predictors of trips and falls.`,
    });
  }

  // 5. Activity volume.
  if (totalMin > 0) {
    let body = `You logged ${totalMin.toFixed(0)} active minutes ${rangeLabel}.`;
    let severity = 'neutral';
    if (prevTotalMin != null) {
      const diff = totalMin - prevTotalMin;
      const pct = prevTotalMin > 0 ? (diff / prevTotalMin) * 100 : null;
      if (pct != null && Math.abs(pct) > 15) {
        body += ` That's ${diff > 0 ? 'up' : 'down'} ${Math.abs(pct).toFixed(0)}% from the previous period.`;
        severity = diff > 0 ? 'positive' : 'concern';
      }
    }
    out.push({ severity, title: 'Active time', body });
  }

  // 6. Cadence consistency.
  if (cadence != null && cadence >= 100 && cadence <= 120) {
    out.push({
      severity: 'positive',
      title: 'Cadence is in the typical walking range',
      body: `Average ${cadence.toFixed(0)} spm — comfortable walking rhythm.`,
    });
  }

  return out.slice(0, 5);  // cap at 5 — UI gets noisy beyond that.
}

export default function InsightsCard({ insights }) {
  if (!insights || !insights.length) {
    return (
      <div className="insights-card">
        <div className="insights-title">Health insights</div>
        <div className="insights-empty">Not enough data yet — keep walking and check back tomorrow.</div>
      </div>
    );
  }

  return (
    <div className="insights-card">
      <div className="insights-title">Health insights</div>
      <ul className="insights-list">
        {insights.map((i, idx) => {
          const cfg = SEVERITY[i.severity] || SEVERITY.neutral;
          return (
            <li key={idx} className="insight-item" style={{ background: cfg.bg }}>
              <div className="insight-dot" style={{ background: cfg.dot }} />
              <div className="insight-body">
                <div className="insight-head" style={{ color: cfg.color }}>{i.title}</div>
                <div className="insight-text">{i.body}</div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
