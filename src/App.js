import { useState, useEffect, useCallback } from 'react';
import GaitCard from './components/GaitCard';
import MetricCard from './components/MetricCard';
import CadenceTrend from './components/CadenceTrend';
import './App.css';

const MAX_POINTS = 20;

function clamp(val, min, max) {
  return Math.min(max, Math.max(min, val));
}

function formatTime(date) {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function classifyGait(cadence, clearance, similarity) {
  if (clearance < 10) return { classification: 'Shuffling', confidence: Math.round(75 + Math.random() * 15) };
  if (cadence < 90 || similarity < 5) return { classification: 'Limping', confidence: Math.round(70 + Math.random() * 20) };
  return { classification: 'Normal', confidence: Math.round(88 + Math.random() * 10) };
}

export default function App() {
  const [cadence, setCadence] = useState(112);
  const [steps, setSteps] = useState(2841);
  const [clearance, setClearance] = useState(18);
  const [similarity, setSimilarity] = useState(8.1);
  const [gait, setGait] = useState({ classification: 'Normal', confidence: 94 });

  const [cadenceHistory, setCadenceHistory] = useState(() => {
    const now = Date.now();
    return Array.from({ length: MAX_POINTS }, (_, i) => ({
      label: formatTime(new Date(now - (MAX_POINTS - 1 - i) * 1500)),
      value: clamp(Math.round(112 + (Math.random() * 12 - 6)), 70, 150),
    }));
  });

  const tick = useCallback(() => {
    setCadence(prev => {
      const next = clamp(Math.round(prev + (Math.random() * 8 - 4)), 70, 150);

      setClearance(c => parseFloat(clamp(c + (Math.random() * 1.5 - 0.75), 5, 35).toFixed(1)));
      setSimilarity(s => parseFloat(clamp(s + (Math.random() * 0.4 - 0.2), 1, 10).toFixed(1)));
      setSteps(st => st + Math.round(Math.random() * 3));

      const newClearance = clamp(clearance + (Math.random() * 1.5 - 0.75), 5, 35);
      const newSimilarity = clamp(similarity + (Math.random() * 0.4 - 0.2), 1, 10);
      setGait(classifyGait(next, newClearance, newSimilarity));

      setCadenceHistory(hist => {
        const updated = [...hist.slice(1), { label: formatTime(new Date()), value: next }];
        return updated;
      });

      return next;
    });
  }, [clearance, similarity]);

  useEffect(() => {
    const id = setInterval(tick, 1500);
    return () => clearInterval(id);
  }, [tick]);

  const avgCadence = Math.round(
    cadenceHistory.reduce((s, p) => s + p.value, 0) / cadenceHistory.length
  );
  const cadenceDiff = cadence - avgCadence;
  const cadenceDelta = cadenceDiff === 0
    ? 'at average'
    : `${cadenceDiff > 0 ? '+' : ''}${cadenceDiff} from avg`;
  const cadenceDeltaType = cadenceDiff > 5 ? 'up' : cadenceDiff < -5 ? 'down' : 'neutral';

  const clearanceDelta =
    clearance < 10 ? 'low — possible shuffle' :
    clearance > 28 ? 'high — check form' : 'normal range';
  const clearanceDeltaType = clearance < 10 ? 'down' : clearance > 28 ? 'down' : 'neutral';

  const historyValues = cadenceHistory.map(p => p.value);
  const historyLabels = cadenceHistory.map(p => p.label);

  return (
    <div className="app">
      <header className="app-header">
        <span className="app-title">SteadyStep</span>
        <div className="live-badge">
          <div className="live-dot" />
          Live
        </div>
      </header>

      <GaitCard
        classification={gait.classification}
        confidence={gait.confidence}
      />

      <div className="metrics-grid">
        <MetricCard
          label="Cadence"
          value={cadence}
          unit="spm"
          delta={cadenceDelta}
          deltaType={cadenceDeltaType}
        />
        <MetricCard
          label="Total steps"
          value={steps.toLocaleString()}
          delta="this session"
          deltaType="neutral"
        />
        <MetricCard
          label="Foot clearance"
          value={clearance.toFixed(1)}
          unit="cm"
          delta={clearanceDelta}
          deltaType={clearanceDeltaType}
        />
        <MetricCard
          label="Gait similarity"
          value={similarity.toFixed(1)}
          unit="/ 10"
          deltaType="neutral"
        >
          <div className="similarity-bar-bg">
            <div
              className="similarity-bar-fill"
              style={{ width: `${(similarity / 10) * 100}%` }}
            />
          </div>
        </MetricCard>
      </div>

      <CadenceTrend history={historyValues} labels={historyLabels} />
    </div>
  );
}