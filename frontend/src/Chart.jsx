import { fmt, dateOf } from './lib.jsx';

// Last 30 days drawn solid; next 14 days as the median with the 10–90% range shaded.
export function ForecastChart({ history, forecast, unitLabel }) {
  if (!history?.length || !forecast?.length) return null;
  const W = 640, H = 220, L = 50, R = 12, T = 16, B = 30;
  const n = history.length + forecast.length - 1, h0 = history.length;
  const max = Math.max(...history.map(h => h.qty), ...forecast.map(f => f.p90)) * 1.12 || 1;
  const X = i => L + (i / n) * (W - L - R), Y = v => T + (1 - v / max) * (H - T - B);
  const band = forecast.map((f, i) => `${X(h0 + i)},${Y(f.p90)}`).join(' ') + ' ' + forecast.map((f, i) => `${X(h0 + i)},${Y(f.p10)}`).reverse().join(' ');
  const ticks = [0, max / 3, (2 * max) / 3];
  const xLabels = [[0, history[0].day], [h0, forecast[0].day], [n, forecast[forecast.length - 1].day]];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Daily use, last 30 days and forecast for the next 14 days">
      {ticks.map(v => <g key={v}><line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} className="c-grid" /><text x={L - 8} y={Y(v) + 4} textAnchor="end" className="c-label">{fmt(v, v < 10 && v > 0 ? 1 : 0)}</text></g>)}
      <polygon points={band} className="c-band" />
      <polyline points={history.map((h, i) => `${X(i)},${Y(h.qty)}`).join(' ')} className="c-hist" />
      <polyline points={[`${X(h0 - 1)},${Y(history[h0 - 1].qty)}`, ...forecast.map((f, i) => `${X(h0 + i)},${Y(f.p50)}`)].join(' ')} className="c-fc" />
      <line x1={X(h0 - 0.5)} x2={X(h0 - 0.5)} y1={T} y2={H - B} className="c-today" />
      {xLabels.map(([i, d], k) => <text key={k} x={X(i)} y={H - 9} textAnchor={k === 0 ? 'start' : k === 2 ? 'end' : 'middle'} className="c-label">{k === 1 ? 'Today' : dateOf(d)}</text>)}
      <text x={L} y={T - 4} className="c-label">{unitLabel} a day</text>
    </svg>
  );
}

export function Convergence({ values, baseline }) {
  if (!values?.length) return null;
  const W = 640, H = 150, L = 50, R = 12, T = 14, B = 26;
  const max = Math.max(baseline, ...values) * 1.08, min = Math.min(...values) * 0.85;
  const X = i => L + (i / Math.max(1, values.length - 1)) * (W - L - R), Y = v => T + (1 - (v - min) / (max - min || 1)) * (H - T - B);
  const last = values[values.length - 1];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Plan cost by generation of the genetic algorithm">
      <line x1={L} x2={W - R} y1={Y(baseline)} y2={Y(baseline)} className="c-base" />
      <text x={W - R} y={Y(baseline) - 6} textAnchor="end" className="c-label">Rule-based plan, {fmt(baseline, 1)}</text>
      <polyline points={values.map((v, i) => `${X(i)},${Y(v)}`).join(' ')} className="c-hist" />
      <circle cx={X(values.length - 1)} cy={Y(last)} r="4" className="c-dot" />
      <text x={X(values.length - 1)} y={Y(last) + 18} textAnchor="end" className="c-label">Optimised, {fmt(last, 1)}</text>
      <text x={L} y={H - 7} className="c-label">Generation 0</text>
      <text x={W - R} y={H - 7} textAnchor="end" className="c-label">{values.length - 1}</text>
    </svg>
  );
}
