import { useEffect, useRef, useState } from 'react';
import { useApi, dateOf } from './lib.jsx';
import MapView, { MapKey, roadDay, zoneDay } from './MapView.jsx';

const LAYERS = [['closure', 'Chance of closure'], ['weather', 'Weather'], ['dangers', 'Dangers'], ['cover', 'Stock at posts']];
const AVAL = { high: 'high', considerable: 'considerable' };
const pct = p => `${Math.round(p * 100)}%`;
const deg = t => `${t < 0 ? '−' : ''}${Math.abs(Math.round(t))} °C`;
const dayName = (iso, i) => (i === 0 ? 'Today' : new Date(iso + 'T00:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric' }));

function summary(map, hz, day) {
  if (!hz) return null;
  const roads = map.roads.features.map(f => f.properties);
  const by = Object.fromEntries(hz.roads.map(r => [r.id, r]));
  const closed = roads.filter(r => r.status === 'closed');
  const likely = roads.filter(r => r.status !== 'closed' && roadDay(by[r.id], r, day).p >= 0.5);
  const aval = roads.filter(r => roadDay(by[r.id], r, day).avalanche === 'high');
  const zs = hz.zones.map(z => ({ z, d: zoneDay(z, day) })).filter(x => x.d).sort((a, b) => b.d.snow_cm - a.d.snow_cm);
  const when = day < 0 ? 'Over the next 3 days' : day === 0 ? 'Today' : `On ${dateOf(hz.days[day])}`;
  const parts = [];
  parts.push(likely.length ? `${likely.length} ${likely.length === 1 ? 'road is' : 'roads are'} likely to close` : 'no open road is likely to close');
  if (closed.length) parts.push(`${closed.length} already closed`);
  if (aval.length) parts.push(`avalanche danger is high on ${aval.length} ${aval.length === 1 ? 'road' : 'roads'}`);
  const top = zs[0];
  const snow = top && top.d.snow_cm >= 1 ? ` Heaviest snow at ${top.z.name}: ${Math.round(top.d.snow_cm)} cm${day < 0 ? ' in total' : ''}.` : ' Little or no snow forecast.';
  return `${when}, ${parts.join(', ')}.${snow}`;
}

function RoadCard({ road, hzRoad, zone, day, days, names, onClose }) {
  const d = roadDay(hzRoad, road, day);
  const zd = zoneDay(zone, day);
  const closed = road.status === 'closed';
  const dangers = [
    d.avalanche && `Avalanche danger ${AVAL[d.avalanche]} (${Math.round(day < 0 ? Math.max(...hzRoad.days.slice(0, 3).map(x => x.snow3_cm)) : hzRoad.days[day].snow3_cm)} cm of snow over 3 days at ${road.alt_m.toLocaleString('en-IN')} m)`,
    ...(hzRoad?.fixed || []).map(f => f.text),
    road.mode === 'animal' && 'Mules only, no vehicles',
  ].filter(Boolean);
  return (
    <div className="road-card" role="region" aria-label={`${road.name} details`}>
      <div className="road-card-head">
        <h3>{road.name}</h3>
        <button type="button" className="text-button" onClick={onClose}>Close</button>
      </div>
      <p className="quiet">Between {names[road.a]} and {names[road.b]} · {road.km} km · highest point {road.alt_m.toLocaleString('en-IN')} m</p>
      <p className={closed ? 't-short' : ''}><strong>{closed ? 'Closed now.' : `${pct(d.p)} chance of closure ${day < 0 ? 'over the next 3 days' : day === 0 ? 'today' : `on ${dateOf(days[day])}`}.`}</strong></p>
      {hzRoad && (
        <ol className="week-strip" aria-label="Chance of closure by day">
          {hzRoad.days.map((x, i) => (
            <li key={x.day} className={i === day ? 'is-day' : ''} title={`${dateOf(x.day)}: ${pct(x.p)}`}>
              <span className="ws-bar" style={{ '--p': x.p }} />
              <span className="ws-n">{Math.round(x.p * 100)}</span>
              <span className="ws-d">{i === 0 ? 'Today' : dateOf(x.day).split(' ')[0]}</span>
            </li>
          ))}
        </ol>
      )}
      {zd && <p>Weather ({zone.name}): {Math.round(zd.snow_cm)} cm snow{zd.span ? ' over 3 days' : ''}, {deg(zd.temp_c)}{zd.span ? ' at coldest' : ''}, wind {zd.wind_kmh} km/h{zd.span ? ' at most' : ''}.</p>}
      {dangers.length ? <ul className="danger-list">{dangers.map(x => <li key={x}>{x}</li>)}</ul> : <p className="quiet">No other dangers recorded.</p>}
    </div>
  );
}

export default function SectorMap({ map, height = 560, onSelect, onRoad, initialLayers }) {
  const hz = useApi('/hazards');
  const [day, setDay] = useState(-1);
  const [layers, setLayers] = useState(initialLayers || { closure: true, weather: true, dangers: true, cover: true });
  const [focus, setFocus] = useState(null);
  const [hover, setHover] = useState(null);
  const [playing, setPlaying] = useState(false);
  const timer = useRef(null);

  useEffect(() => {
    if (!playing) return;
    timer.current = setInterval(() => setDay(d => {
      if (d >= 6) { setPlaying(false); return 6; }
      return d + 1;
    }), 1100);
    return () => clearInterval(timer.current);
  }, [playing]);

  const H = hz.data;
  const names = Object.fromEntries(map.bases.features.map(f => [f.properties.id, f.properties.name.split(' ').slice(-1)[0]]));
  const shown = focus || hover;
  const road = shown && map.roads.features.find(f => f.properties.id === shown)?.properties;
  const hzRoad = road && H?.roads.find(r => r.id === road.id);
  const zone = hzRoad && H.zones.find(z => z.zone === hzRoad.zone);

  return (
    <div className="sector-map">
      <div className="map-controls">
        <div className="day-pick" role="group" aria-label="Forecast day">
          <button type="button" aria-pressed={day === -1} onClick={() => { setPlaying(false); setDay(-1); }}>Next 3 days</button>
          {(H?.days || []).map((d, i) => (
            <button key={d} type="button" aria-pressed={day === i} onClick={() => { setPlaying(false); setDay(i); }}>{dayName(d, i)}</button>
          ))}
          {H && <button type="button" className="play" aria-pressed={playing} onClick={() => { if (!playing && (day < 0 || day >= 6)) setDay(0); setPlaying(!playing); }}>
            {playing ? 'Pause' : 'Play the week'}
          </button>}
        </div>
        <div className="layer-pick" role="group" aria-label="Map layers">
          {LAYERS.map(([k, label]) => (
            <label key={k}><input type="checkbox" checked={layers[k]} onChange={e => setLayers({ ...layers, [k]: e.target.checked })} />{label}</label>
          ))}
        </div>
      </div>
      {H && <p className="map-summary" aria-live="polite">{summary(map, H, day)}</p>}
      {hz.error && <p className="note">Weather and danger layers are unavailable: {hz.error}</p>}
      <div className="map-stage">
        <MapView data={map} height={height} hz={H} day={day} layers={layers} onSelect={onSelect} focusRoad={shown}
          onRoad={r => { setFocus(r.id === focus ? null : r.id); onRoad && onRoad(r); }} onRoadHover={setHover} />
        {road && <RoadCard road={road} hzRoad={hzRoad} zone={zone} day={day} days={H?.days || []} names={names} onClose={() => { setFocus(null); setHover(null); }} />}
      </div>
      {layers.weather && H && (
        <ul className="zone-list" aria-label="Weather by zone">
          {H.zones.map(z => { const d = zoneDay(z, day); return d ? <li key={z.zone}><strong>{z.name}</strong> {Math.round(d.snow_cm)} cm snow{d.span ? ' in 3 days' : ''}, {deg(d.temp_c)}, wind {d.wind_kmh} km/h</li> : null; })}
        </ul>
      )}
      <MapKey layers={{ ...layers, weather: layers.weather && !!H, forecast: !!H }} />
      {layers.dangers && H && <p className="note">Avalanche danger is a field rule, not a model. {H.rules.avalanche} Chances of closure come from the road model and the weather forecast. Click or hover over a road for details.</p>}
    </div>
  );
}
