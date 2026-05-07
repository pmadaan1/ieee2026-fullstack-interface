import { useEffect, useRef } from 'react';
import {
  Chart,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  Filler,
  Tooltip,
} from 'chart.js';
import './CadenceTrend.css';

Chart.register(LineController, LineElement, PointElement, LinearScale, CategoryScale, Filler, Tooltip);

const TARGET_MIN = 100;
const TARGET_MAX = 120;
const MAX_POINTS = 20;

export default function CadenceTrend({ history, labels }) {
  const canvasRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (chartRef.current) {
      chartRef.current.destroy();
      chartRef.current = null;
    }

    const ctx = canvasRef.current.getContext('2d');

    chartRef.current = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Target max',
            data: Array(MAX_POINTS).fill(TARGET_MAX),
            borderColor: 'rgba(99,153,34,0.3)',
            borderWidth: 1,
            borderDash: [4, 4],
            pointRadius: 0,
            fill: '+1',
            backgroundColor: 'rgba(99,153,34,0.08)',
          },
          {
            label: 'Target min',
            data: Array(MAX_POINTS).fill(TARGET_MIN),
            borderColor: 'rgba(99,153,34,0.3)',
            borderWidth: 1,
            borderDash: [4, 4],
            pointRadius: 0,
            fill: false,
          },
          {
            label: 'Cadence',
            data: history,
            borderColor: '#378ADD',
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: '#378ADD',
            fill: false,
            tension: 0.35,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) =>
                ctx.datasetIndex === 2 ? `${ctx.parsed.y} spm` : null,
            },
            filter: (item) => item.datasetIndex === 2,
          },
        },
        scales: {
          x: {
            grid: { color: 'rgba(0,0,0,0.05)' },
            ticks: { font: { size: 11 }, color: '#888', maxTicksLimit: 8 },
          },
          y: {
            min: 70,
            max: 150,
            grid: { color: 'rgba(0,0,0,0.05)' },
            ticks: {
              font: { size: 11 },
              color: '#888',
              callback: (v) => `${v}`,
            },
          },
        },
      },
    });

    return () => {
      if (chartRef.current) {
        chartRef.current.destroy();
        chartRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!chartRef.current) return;
    chartRef.current.data.labels = labels;
    chartRef.current.data.datasets[0].data = Array(labels.length).fill(TARGET_MAX);
    chartRef.current.data.datasets[1].data = Array(labels.length).fill(TARGET_MIN);
    chartRef.current.data.datasets[2].data = history;
    chartRef.current.update('none');
  }, [history, labels]);

  return (
    <div className="cadence-card">
      <div className="cadence-header">
        <span className="cadence-title">Cadence trend</span>
        <span className="cadence-range">Last 20 readings</span>
      </div>
      <div className="cadence-legend">
        <span className="legend-item">
          <span className="legend-dot" style={{ background: '#378ADD' }} />
          Cadence
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: 'rgba(99,153,34,0.5)' }} />
          Target zone (100–120 spm)
        </span>
      </div>
      <div className="cadence-chart-wrap">
        <canvas
          ref={canvasRef}
          role="img"
          aria-label="Line chart of cadence over time with target zone between 100 and 120 steps per minute."
        >
          Cadence trend showing measured steps per minute vs. target zone.
        </canvas>
      </div>
    </div>
  );
}