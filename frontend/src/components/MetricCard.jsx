import './MetricCard.css';

export default function MetricCard({ label, value, unit, delta, deltaType = 'neutral', accent, children }) {
  const deltaClass = {
    up: 'delta-up',
    down: 'delta-down',
    neutral: 'delta-neutral',
  }[deltaType];

  const cardClass = `metric-card${accent ? ` metric-card--${accent}` : ''}`;

  return (
    <div className={cardClass}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">
        {value}
        {unit && <span className="metric-unit">{unit}</span>}
      </div>
      {delta && <div className={`metric-delta ${deltaClass}`}>{delta}</div>}
      {children}
    </div>
  );
}