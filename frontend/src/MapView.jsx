import { useEffect, useMemo, useRef, useState } from 'react';
import { geoMercator, geoPath } from 'd3-geo';
import { select } from 'd3-selection';
import { zoom, zoomIdentity } from 'd3-zoom';
import { shortName, lasts } from './lib.jsx';

// Survey-sheet map drawn from PostGIS GeoJSON, with no tile server, so it works offline.
// Optional layers from /api/hazards for a chosen day:
//   closure  - chance of closure on every road, and road colour by that chance
//   weather  - snow lying along roads, and a weather card for each zone
//   dangers  - avalanche danger, enemy observation, bridge limits and high passes
//   cover    - days of stock under each post
// day = -1 means "next 3 days", the view the planner uses (each road's highest chance over 3 days).

const LEVEL = p => (p >= 0.5 ? 'likely' : p >= 0.2 ? 'risky' : 'low');
// Where each zone's weather card is centred (lon, lat): open ground beside that zone's roads.
const ZONE_CARD = { valley: [77.70, 34.10], tangla: [78.25, 34.45], zarla: [77.61, 34.60], high: [78.27, 34.79] };

export function roadDay(hzRoad, r, day) {
  // Chance of closure, snow and avalanche danger for one road on the chosen day.
  if (!hzRoad) return { p: r.risk, avalanche: null };
  if (day < 0) {
    const next = hzRoad.days.slice(0, 3);
    const order = { high: 2, considerable: 1 };
    const worst = next.reduce((a, d) => ((order[d.avalanche] || 0) > (order[a] || 0) ? d.avalanche : a), null);
    return { p: r.risk, avalanche: worst, snow_cm: next.reduce((s, d) => s + d.snow_cm, 0) };
  }
  const d = hzRoad.days[day];
  return { p: d ? d.p : r.risk, avalanche: d?.avalanche || null, snow_cm: d?.snow_cm || 0 };
}

export function zoneDay(zone, day) {
  if (!zone) return null;
  if (day < 0) {
    const next = zone.days.slice(0, 3);
    return { snow_cm: next.reduce((s, d) => s + d.snow_cm, 0), temp_c: Math.min(...next.map(d => d.temp_c)), wind_kmh: Math.max(...next.map(d => d.wind_kmh)), span: true };
  }
  return zone.days[day];
}

function along(pts, frac) {
  // Point and direction at a fraction of a projected polyline's length.
  const seg = [];
  let total = 0;
  for (let i = 1; i < pts.length; i++) { const l = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]); seg.push(l); total += l; }
  let goal = total * frac;
  for (let i = 0; i < seg.length; i++) {
    if (goal <= seg[i] || i === seg.length - 1) {
      const f = seg[i] ? Math.min(1, goal / seg[i]) : 0, a = pts[i], b = pts[i + 1];
      return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
    }
    goal -= seg[i];
  }
  return pts[0];
}

function Snowflake({ size = 12 }) {
  const r = size / 2;
  return (
    <g className="ico-snow">
      {[0, 60, 120].map(a => <line key={a} x1={-r} y1={0} x2={r} y2={0} transform={`rotate(${a})`} />)}
    </g>
  );
}

function DangerIcon({ kind, level, limit }) {
  if (kind === 'avalanche') {
    return (
      <g className={`ico-aval aval-${level}`}>
        <path d="M0 -8 L8.5 7 H-8.5 Z" />
        <path d="M-5 4.5 L1.5 -2 L5 4.5" className="ico-aval-slope" />
        <circle cx="-1.6" cy="1.8" r="1" className="ico-aval-dot" />
      </g>
    );
  }
  if (kind === 'observation') {
    return (
      <g className={`ico-obs obs-${level}`}>
        <circle r="8.5" />
        <path d="M-5.5 0 Q0 -5 5.5 0 Q0 5 -5.5 0 Z" className="ico-obs-eye" />
        <circle r="1.8" className="ico-obs-pupil" />
      </g>
    );
  }
  if (kind === 'bridge') {
    return (
      <g className="ico-bridge">
        <circle r="9.5" />
        <text y="3.2" textAnchor="middle">{`${limit}t`}</text>
      </g>
    );
  }
  return null;
}

export default function MapView({ data, height = 520, selected, onSelect, trip, onRoad, onRoadHover, focusRoad, showCover = true, hz, day = -1, layers }) {
  const wrap = useRef(null), svg = useRef(null), zb = useRef(null);
  const [w, setW] = useState(800);
  const [t, setT] = useState(zoomIdentity);
  const L = { closure: !!layers?.closure, weather: !!layers?.weather && !!hz, dangers: !!layers?.dangers, cover: layers ? !!layers.cover : showCover };

  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    zb.current = zoom().scaleExtent([0.8, 8]).on('zoom', e => setT(e.transform));
    select(svg.current).call(zb.current).on('dblclick.zoom', null);
  }, []);

  const M = w < 560 ? 26 : 34, ML = w < 600 ? 58 : 74; // margins for graticule labels (latitude labels need more room)
  const small = w < 560;
  const H = small ? Math.max(270, Math.round(w * 0.95)) : Math.min(height, Math.max(320, Math.round(w * 0.95)));
  const pad = small ? 10 : 24, padR = small ? 64 : 84;
  const { proj, path, grid } = useMemo(() => {
    const feats = [...(data?.roads.features || []), ...(data?.bases.features || [])];
    const p = geoMercator();
    if (feats.length) p.fitExtent([[ML + pad, M + pad], [Math.max(160, w - M - padR), H - M - pad - 6]], { type: 'FeatureCollection', features: feats });
    const [lon0, lat1] = p.invert([ML, M]), [lon1, lat0] = p.invert([w - M, H - M]);
    const tenMin = Math.abs(p([0, 0])[0] - p([1 / 6, 0])[0]);
    const step = tenMin >= 70 ? 1 / 6 : tenMin >= 35 ? 1 / 3 : 1 / 2; // 10, 20 or 30 minutes, whichever leaves room for labels
    const lons = [], lats = [];
    for (let v = Math.ceil(lon0 / step) * step; v < lon1; v += step) lons.push(v);
    for (let v = Math.ceil(lat0 / step) * step; v < lat1; v += step) lats.push(v);
    return { proj: p, path: geoPath(p), grid: { lons, lats } };
  }, [data, w, H, ML, pad, padR]);

  const roads = data?.roads.features || [];
  const pts = useMemo(() => Object.fromEntries(roads.map(f => [f.properties.id, f.geometry.coordinates.map(c => proj(c))])), [roads, proj]);
  const hzRoads = useMemo(() => Object.fromEntries((hz?.roads || []).map(r => [r.id, r])), [hz]);
  const zones = useMemo(() => Object.fromEntries((hz?.zones || []).map(z => [z.zone, z])), [hz]);

  const dm = (v, pos, neg) => { const a = Math.abs(v), d = Math.floor(a + 1e-9), m = Math.round((a - d) * 60); return `${d}°${String(m).padStart(2, '0')}′${v >= 0 ? pos : neg}`; };
  const k = t.k;
  const tripRoads = new Set((trip?.legs || []).flatMap(l => l.roads || []));
  const heli = (trip?.legs || []).filter(l => l.heli);
  const at = id => proj(data.bases.features.find(f => f.properties.id === id).geometry.coordinates);
  const scr = p => t.apply(p);
  const narrow = w < 560;

  const anchors = hz ? Object.fromEntries(Object.entries(ZONE_CARD).map(([z, ll]) => [z, proj(ll)])) : {};

  return (
    <div className="map" ref={wrap} style={{ height: H }}>
      <svg ref={svg} width={w} height={H} role="img" aria-label="Map of the sector">
        <defs><clipPath id="sheet"><rect x={ML} y={M} width={Math.max(0, w - ML - M)} height={H - 2 * M} /></clipPath></defs>
        <rect x={ML} y={M} width={Math.max(0, w - ML - M)} height={H - 2 * M} className="sheet" />
        <g clipPath="url(#sheet)">
          <g transform={t.toString()}>
            {grid.lons.map(v => { const [x] = proj([v, 0]); return <line key={'x' + v} x1={x} x2={x} y1={-4000} y2={4000} className="grat" strokeWidth={1 / k} />; })}
            {grid.lats.map(v => { const [, y] = proj([0, v]); return <line key={'y' + v} x1={-4000} x2={6000} y1={y} y2={y} className="grat" strokeWidth={1 / k} />; })}

            {/* snow lying along each road, from its zone's forecast */}
            {L.weather && roads.map(f => {
              const z = zoneDay(zones[hzRoads[f.properties.id]?.zone], day);
              if (!z || z.snow_cm < 2) return null;
              const s = Math.min(z.snow_cm, 60);
              return <path key={'snow' + f.properties.id} d={path(f)} className="snow-band" strokeWidth={(8 + s * 0.45) / k} style={{ opacity: Math.min(0.75, 0.18 + s / 50) }} />;
            })}
            {/* enemy observation: a hatched halo along exposed roads */}
            {L.dangers && roads.map(f => {
              const ob = hzRoads[f.properties.id]?.fixed.find(x => x.kind === 'observation') || (!hz && f.properties.exposure >= 0.3 && { level: f.properties.exposure >= 0.6 ? 'high' : 'moderate' });
              return ob ? <path key={'obs' + f.properties.id} d={path(f)} className={`obs-band obs-${ob.level}`} strokeWidth={13 / k} strokeDasharray={`${2 / k} ${4 / k}`} /> : null;
            })}

            {roads.map(f => {
              const r = f.properties, closed = r.status === 'closed';
              const { p } = roadDay(hzRoads[r.id], r, day);
              const lvl = closed ? 'is-closed' : L.closure ? `is-${LEVEL(p)}` : r.risk >= 0.4 ? 'is-risky' : '';
              return (
                <g key={r.id} className={`road${onRoad || onRoadHover ? ' is-clickable' : ''}${focusRoad === r.id ? ' is-focus' : ''}`}
                  onClick={() => onRoad && onRoad(r)} onMouseEnter={() => onRoadHover && onRoadHover(r.id)} onMouseLeave={() => onRoadHover && onRoadHover(null)}>
                  <path d={path(f)} className="road-hit" strokeWidth={16 / k} />
                  {focusRoad === r.id && <path d={path(f)} className="road-focus" strokeWidth={9 / k} />}
                  {tripRoads.has(r.id) && <path d={path(f)} className="road-trip" strokeWidth={10 / k} />}
                  <path d={path(f)} className={`road-line ${lvl}${r.mode === 'animal' ? ' is-track' : ''}`}
                    strokeWidth={(r.mode === 'animal' ? 1.8 : 2.8) / k} strokeDasharray={closed ? `${7 / k} ${5 / k}` : r.mode === 'animal' ? `${2 / k} ${4 / k}` : null}>
                    <title>{`${r.name}: ${closed ? 'closed' : `open, ${Math.round(p * 100)}% chance of closure`}${r.max_kg ? `, bridge limit ${r.max_kg / 1000} t` : ''}`}</title>
                  </path>
                </g>
              );
            })}
            {heli.map((l, i) => { const [x1, y1] = at(l.from), [x2, y2] = at(l.to); return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} className="heli" strokeWidth={2.4 / k} strokeDasharray={`${9 / k} ${6 / k}`} />; })}
            {data && data.bases.features.map(f => {
              const b = f.properties, [x, y] = proj(f.geometry.coordinates), s = (b.kind === 'post' ? 7 : 9) / k;
              const lvl = b.kind === 'base' ? 'base' : b.status === 'crit' ? 'short' : b.status === 'warn' ? 'low' : 'ok';
              return (
                <g key={b.id} className={`site site-${b.kind} lvl-${lvl}${selected === b.id ? ' is-selected' : ''}${onSelect ? ' is-clickable' : ''}`} transform={`translate(${x},${y})`}
                  onClick={() => onSelect && onSelect(b.id)} tabIndex={onSelect ? 0 : -1} role={onSelect ? 'link' : undefined} aria-label={b.name}
                  onKeyDown={e => onSelect && e.key === 'Enter' && onSelect(b.id)}>
                  {selected === b.id && <circle r={s * 2.2} className="halo" strokeWidth={1.6 / k} />}
                  {b.kind === 'post' ? <circle r={s} strokeWidth={1.8 / k} /> : <rect x={-s} y={-s} width={s * 2} height={s * 2} strokeWidth={1.8 / k} />}
                  <text x={s + 6 / k} y={4 / k} fontSize={14 / k} className="site-name">{shortName(b.name)}</text>
                  {L.cover && !narrow && b.kind !== 'base' && <text x={s + 6 / k} y={18 / k} fontSize={11.5 / k} className="site-note">{lasts(b.worst_days)}</text>}
                </g>
              );
            })}
          </g>

          {/* screen-space labels: stay the same size when zooming */}
          {L.dangers && roads.map(f => {
            const r = f.properties, hr = hzRoads[r.id];
            const pass = hr?.fixed.find(x => x.kind === 'pass');
            if (!pass || narrow) return null;
            const [x, y] = scr(along(pts[r.id], 0.3));
            const [label, alt] = pass.text.split(' pass, ');
            return (
              <g key={'pass' + r.id} className="pass" transform={`translate(${x},${y})`} pointerEvents="none">
                <path d="M0 -6 L6 5 H-6 Z" />
                <text x="9" y="-2">{label}</text>
                <text x="9" y="10" className="pass-alt">{alt}</text>
              </g>
            );
          })}
          {L.dangers && roads.map(f => {
            const r = f.properties, hr = hzRoads[r.id];
            const { avalanche } = roadDay(hr, r, day);
            const icons = [];
            if (avalanche) icons.push({ kind: 'avalanche', level: avalanche });
            for (const x of hr?.fixed || (r.exposure >= 0.3 ? [{ kind: 'observation', level: r.exposure >= 0.6 ? 'high' : 'moderate' }] : [])) if (x.kind === 'observation') icons.push(x);
            if (r.max_kg) icons.push({ kind: 'bridge', limit: r.max_kg / 1000 });
            if (!icons.length) return null;
            const [x, y] = scr(along(pts[r.id], L.closure ? 0.68 : 0.5));
            return (
              <g key={'dz' + r.id} transform={`translate(${x - (icons.length - 1) * 11},${y})`} className="dangers" onClick={() => onRoad && onRoad(r)} style={{ cursor: onRoad ? 'pointer' : 'default' }}>
                {icons.map((ic, i) => <g key={i} transform={`translate(${i * 22},0)`}><DangerIcon kind={ic.kind} level={ic.level} limit={ic.limit} /></g>)}
              </g>
            );
          })}
          {L.closure && roads.map(f => {
            const r = f.properties, closed = r.status === 'closed';
            const { p } = roadDay(hzRoads[r.id], r, day);
            if (narrow && !closed && p < 0.05 && focusRoad !== r.id) return null;
            const [x, y] = scr(along(pts[r.id], 0.5));
            const text = closed ? 'Closed' : `${Math.round(p * 100)}%`;
            const wid = text.length * 6.6 + 10;
            return (
              <g key={'pill' + r.id} className={`pill pill-${closed ? 'closed' : LEVEL(p)}${focusRoad === r.id ? ' is-focus' : ''}`} transform={`translate(${x},${y})`}
                onClick={() => onRoad && onRoad(r)} onMouseEnter={() => onRoadHover && onRoadHover(r.id)} onMouseLeave={() => onRoadHover && onRoadHover(null)} style={{ cursor: onRoad ? 'pointer' : 'default' }}>
                <rect x={-wid / 2} y={-9} width={wid} height={18} rx={9} />
                <text y={4} textAnchor="middle">{text}</text>
              </g>
            );
          })}
          {L.weather && !narrow && Object.entries(anchors).map(([z, a]) => {
            const zd = zoneDay(zones[z], day);
            if (!zd) return null;
            const [x0, y0] = scr(a);
            const cw = 168, ch = 50;
            const x = Math.max(ML + 4, Math.min(w - M - cw - 4, x0 - cw / 2));
            const y = Math.max(M + 4, Math.min(H - M - ch - 4, y0 - ch / 2));
            const heavy = zd.snow_cm >= 15;
            return (
              <g key={'wx' + z} className={`wx${heavy ? ' wx-heavy' : ''}`} transform={`translate(${x},${y})`} pointerEvents="none">
                <rect width={cw} height={ch} rx={5} />
                <text x={8} y={14} className="wx-zone">{zones[z].name}</text>
                <g transform="translate(15,30)"><Snowflake size={11} /></g>
                <text x={25} y={34} className="wx-snow">{`${Math.round(zd.snow_cm)} cm${zd.span ? ' in 3 days' : ''}`}</text>
                <text x={8} y={46} className="wx-meta">{`${zd.temp_c > 0 ? '' : '−'}${Math.abs(Math.round(zd.temp_c))} °C · wind ${zd.wind_kmh} km/h`}</text>
              </g>
            );
          })}
        </g>
        {grid.lons.map(v => { const x = t.applyX(proj([v, 0])[0]); return x > ML + 24 && x < w - M - 24 ? <text key={'lx' + v} x={x} y={M - 9} textAnchor="middle" className="grat-label">{dm(v, 'E', 'W')}</text> : null; })}
        {grid.lats.map(v => { const y = t.applyY(proj([0, v])[1]); return y > M + 12 && y < H - M - 6 ? <text key={'ly' + v} x={ML - 6} y={y + 4} textAnchor="end" className="grat-label">{dm(v, 'N', 'S').replace(/°/, '° ')}</text> : null; })}
        <rect x={ML} y={M} width={Math.max(0, w - ML - M)} height={H - 2 * M} className="sheet-edge" />
      </svg>
      <button className="map-reset" type="button" onClick={() => select(svg.current).call(zb.current.transform, zoomIdentity)}>Reset zoom</button>
    </div>
  );
}

export function MapKey({ layers }) {
  const L = layers || { cover: true };
  return (
    <div className="map-key">
      <p className="key-row">
        <span><i className="k-dot k-short" />Runs short within 3 days</span>
        <span><i className="k-dot k-low" />Within a week</span>
        <span><i className="k-dot k-ok" />Covered</span>
        <span><i className="k-sq" />Depot</span>
        <span><i className="k-line k-track" />Mule track</span>
      </p>
      <p className="key-row">
        {L.closure
          ? <>
            <span><i className="k-pill k-pill-low">5%</i>Under 20% chance of closure</span>
            <span><i className="k-pill k-pill-risky">35%</i>20–50%</span>
            <span><i className="k-pill k-pill-likely">80%</i>Likely to close</span>
            <span><i className="k-line k-closed" />Closed now</span>
          </>
          : <>
            <span><i className="k-line k-risky" />Road likely to close</span>
            <span><i className="k-line k-closed" />Closed</span>
          </>}
      </p>
      {(L.weather || L.dangers) && (
        <p className="key-row">
          {L.weather && <span><i className="k-snow" />Snow along the road</span>}
          {L.dangers && <>
            {L.forecast && <>
              <span><svg className="k-ico" viewBox="-10 -10 20 20"><DangerIcon kind="avalanche" level="high" /></svg>Avalanche danger, high</span>
              <span><svg className="k-ico" viewBox="-10 -10 20 20"><DangerIcon kind="avalanche" level="considerable" /></svg>Considerable</span>
            </>}
            <span><svg className="k-ico" viewBox="-10 -10 20 20"><DangerIcon kind="observation" level="high" /></svg>Under enemy observation</span>
            <span><svg className="k-ico" viewBox="-11 -11 22 22"><DangerIcon kind="bridge" limit="2.5" /></svg>Bridge weight limit</span>
            {L.forecast && <span><svg className="k-ico" viewBox="-8 -8 16 16"><g className="pass"><path d="M0 -6 L6 5 H-6 Z" /></g></svg>High pass</span>}
          </>}
        </p>
      )}
    </div>
  );
}
