import { useEffect, useRef } from 'react';
import {
  Chart, LineController, LineElement, PointElement, LinearScale,
  CategoryScale, Filler, Tooltip,
} from 'chart.js';

Chart.register(LineController, LineElement, PointElement, LinearScale,
               CategoryScale, Filler, Tooltip);

export default function TimeSeriesChart({
  title, range, labels, values, unit, color = '#1668C1',
  yMin, yMax, targetMin, targetMax,
}) {
  const canvasRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (chartRef.current) { chartRef.current.destroy(); chartRef.current = null; }
    const ctx = canvasRef.current.getContext('2d');

    const datasets = [];
    if (targetMin != null && targetMax != null) {
      datasets.push({
        label: 'Target max', data: Array(labels.length).fill(targetMax),
        borderColor: 'rgba(15,166,114,0.35)', borderWidth: 1, borderDash: [4, 4],
        pointRadius: 0, fill: '+1', backgroundColor: 'rgba(15,166,114,0.07)',
      });
      datasets.push({
        label: 'Target min', data: Array(labels.length).fill(targetMin),
        borderColor: 'rgba(15,166,114,0.35)', borderWidth: 1, borderDash: [4, 4],
        pointRadius: 0, fill: false,
      });
    }
    datasets.push({
      label: title, data: values,
      borderColor: color, borderWidth: 2.4,
      pointRadius: labels.length > 50 ? 0 : 2,
      pointBackgroundColor: color,
      backgroundColor: color + '14',
      fill: true, tension: 0.3, spanGaps: true,
    });

    chartRef.current = new Chart(ctx, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: { duration: 250 },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) =>
                ctx.dataset.label === title
                  ? `${ctx.parsed.y?.toFixed(unit === 'spm' ? 0 : 2)}${unit ? ' ' + unit : ''}`
                  : null,
            },
            filter: (item) => item.dataset.label === title,
          },
        },
        scales: {
          x: {
            grid: { color: 'rgba(0,0,0,0.04)' },
            ticks: { font: { size: 10 }, color: '#6F89A6', maxTicksLimit: 6 },
          },
          y: {
            min: yMin, max: yMax,
            grid: { color: 'rgba(0,0,0,0.05)' },
            ticks: { font: { size: 10 }, color: '#6F89A6' },
          },
        },
      },
    });
    return () => { chartRef.current?.destroy(); chartRef.current = null; };
  }, [title, labels, values, unit, color, yMin, yMax, targetMin, targetMax]);

  return (
    <div className="ts-card">
      <div className="ts-header">
        <span className="ts-title">{title}</span>
        <span className="ts-range">{range}</span>
      </div>
      <div className="ts-chart-wrap">
        <canvas ref={canvasRef} role="img" aria-label={`${title} over time`} />
      </div>
    </div>
  );
}
