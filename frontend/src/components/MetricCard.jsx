import './MetricCard.css';

export default function MetricCard({ label, value, unit, delta, deltaType = 'neutral', children }) {
  const deltaClass = {
    up: 'delta-up',
    down: 'delta-down',
    neutral: 'delta-neutral',
  }[deltaType];

  return (
    <div className="metric-card">
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