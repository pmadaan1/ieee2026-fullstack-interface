// Colored stacked bar showing the % time/probability across activity classes.
// Used in both LiveView (instantaneous distribution from the model) and
// LongTermView (aggregated counts over a period).

const PALETTE = {
  Walking:  '#1668C1',
  Turning:  '#4FA0EE',
  Stairs:   '#0FA672',
  Standing: '#9AAEC4',
  Sitting:  '#6F89A6',
  Idle:     '#9AAEC4',
  Unknown:  '#C9D5E2',
};

export default function ActivityBreakdownBar({
  distribution,
  title = 'Activity breakdown',
  minSegmentPct = 1,
  size = 'md',           // 'sm' | 'md' | 'lg'
  showLegend = true,
}) {
  if (!distribution || Object.keys(distribution).length === 0) {
    return (
      <div className={`act-card act-card--${size}`}>
        {title && <div className="act-title">{title}</div>}
        <div className="act-empty">awaiting data</div>
      </div>
    );
  }

  const total = Object.values(distribution).reduce((s, v) => s + v, 0);
  if (total <= 0) {
    return (
      <div className={`act-card act-card--${size}`}>
        {title && <div className="act-title">{title}</div>}
        <div className="act-empty">no activity yet</div>
      </div>
    );
  }

  const entries = Object.entries(distribution)
    .map(([k, v]) => [k, (v / total) * 100])
    .filter(([, pct]) => pct >= minSegmentPct)
    .sort((a, b) => b[1] - a[1]);

  return (
    <div className={`act-card act-card--${size}`}>
      {title && <div className="act-title">{title}</div>}
      <div className="act-bar">
        {entries.map(([k, pct]) => (
          <div key={k}
               className="act-bar-seg"
               style={{ width: `${pct}%`, background: PALETTE[k] || '#9AAEC4' }}
               title={`${k}: ${pct.toFixed(1)}%`}>
            {pct >= 12 && <span className="act-bar-label">{Math.round(pct)}%</span>}
          </div>
        ))}
      </div>
      {showLegend && (
        <div className="act-legend">
          {entries.map(([k, pct]) => (
            <span key={k} className="act-legend-item">
              <span className="act-legend-dot" style={{ background: PALETTE[k] || '#9AAEC4' }} />
              {k} <strong>{pct.toFixed(0)}%</strong>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
