import './GaitCard.css';

const CONFIG = {
  Normal:    { bg: '#eaf3de', color: '#3b6d11', icon: 'check' },
  Limping:   { bg: '#faeeda', color: '#854f0b', icon: 'warn'  },
  Shuffling: { bg: '#faece7', color: '#993c1d', icon: 'alert' },
};

function Icon({ type, color }) {
  if (type === 'check') return (
    <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.8"
      strokeLinecap="round" strokeLinejoin="round" width="22" height="22">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
  if (type === 'warn') return (
    <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.8"
      strokeLinecap="round" strokeLinejoin="round" width="22" height="22">
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
    </svg>
  );
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.8"
      strokeLinecap="round" strokeLinejoin="round" width="22" height="22">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  );
}

export default function GaitCard({ classification = 'Normal', confidence = 94 }) {
  const cfg = CONFIG[classification] || CONFIG.Normal;

  return (
    <div className="gait-card" style={{ background: cfg.bg }}>
      <div className="gait-left">
        <div className="gait-label">Gait classification</div>
        <div className="gait-class" style={{ color: cfg.color }}>{classification}</div>
        <div className="gait-conf">Confidence: {confidence}%</div>
      </div>
      <div className="gait-circle" style={{ background: cfg.color }}>
        <Icon type={cfg.icon} color="#fff" />
      </div>
    </div>
  );
}