import { useState } from 'react';
import { api, useApi, useApp, Loading, Problem, fmt } from '../lib.jsx';
import SectorMap from '../SectorMap.jsx';

export default function Roads() {
  const { bump, say } = useApp();
  const roads = useApi('/roads');
  const map = useApi('/map');
  const bases = useApi('/bases');
  const [risk, setRisk] = useState({});
  const [focus, setFocus] = useState(null);
  if (roads.error) return <div className="page"><Problem error={roads.error} /></div>;
  if (!roads.data || !map.data) return <div className="page"><Loading /></div>;
  const name = id => bases.data?.find(b => b.id === id)?.name.split(' ').slice(-1)[0] || id;

  const toggle = async r => {
    const status = r.status === 'closed' ? 'open' : 'closed';
    try { await api(`/roads/${r.id}`, { method: 'PATCH', body: { status } }); say(`${r.name} ${status === 'closed' ? 'closed. Plans will route around it.' : 'reopened.'}`); bump(); }
    catch (e) { say(e.message, true); }
  };
  const saveRisk = async r => {
    const v = Number(risk[r.id]);
    if (risk[r.id] === '' || Number.isNaN(v) || v < 0 || v > 100) { say('Chance of closure must be between 0 and 100.', true); return; }
    try { await api(`/roads/${r.id}`, { method: 'PATCH', body: { risk: v / 100 } }); setRisk({ ...risk, [r.id]: undefined }); say(`${r.name}: chance of closure set to ${v}%.`); bump(); }
    catch (e) { say(e.message, true); }
  };
  const remodel = async () => {
    try { await api('/predict/roads/refresh', { body: {} }); setRisk({}); say('Chances of closure reset from the road model.'); bump(); }
    catch (e) { say(e.message, true); }
  };
  const order = [...roads.data].sort((a, b) => (b.status === 'closed') - (a.status === 'closed') || b.risk - a.risk);

  return (
    <div className="page">
      <h1>Roads</h1>
      <p className="intro">The road network the planner routes over. Chances of closure come from the road model and the weather forecast; overwrite one when an engineer report says otherwise. Close a road when it is actually blocked. Pick a day to see how the forecast storm moves through, and click a road on the map for its details.</p>
      <p><button type="button" className="button secondary" onClick={remodel}>Take chances from the model again</button></p>
      <section className="roads-map">
        <SectorMap map={map.data} height={520} initialLayers={{ closure: true, weather: true, dangers: true, cover: false }}
          onRoad={r => { setFocus(r.id); document.getElementById(`road-${r.id}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }} />
      </section>
      <div className="table-wrap">
        <table className="ledger">
          <thead><tr><th>Road</th><th>Between</th><th className="n">Length</th><th className="n">Highest point</th><th>Notes</th><th>Chance of closure, next 3 days</th><th>Status</th></tr></thead>
          <tbody>
            {order.map(r => (
              <tr key={r.id} id={`road-${r.id}`} className={focus === r.id ? 'is-current' : ''}>
                <td>{r.name}</td>
                <td>{name(r.a)} and {name(r.b)}</td>
                <td className="n">{fmt(r.km)} km</td>
                <td className="n">{fmt(r.alt_m)} m</td>
                <td className="quiet">{[r.mode === 'animal' && 'Mules only', r.max_kg && `Bridge limit ${r.max_kg / 1000} t`, r.exposure >= 0.3 && 'Under observation'].filter(Boolean).join('. ') || '–'}</td>
                <td>
                  <span className="inline-edit">
                    <input type="number" min="0" max="100" aria-label={`Chance of closure for ${r.name}, percent`} value={risk[r.id] ?? Math.round(r.risk * 100)} onChange={e => setRisk({ ...risk, [r.id]: e.target.value })} onKeyDown={e => e.key === 'Enter' && saveRisk(r)} />%
                    {risk[r.id] !== undefined && <button type="button" className="text-button" onClick={() => saveRisk(r)}>Save</button>}
                  </span>
                  <small className="quiet source">{r.risk_source === 'manual' ? 'set by hand' : 'from the model'}</small>
                </td>
                <td className="row-action">
                  <span className={r.status === 'closed' ? 't-short' : ''}>{r.status === 'closed' ? 'Closed' : 'Open'}</span>{' '}
                  <button type="button" className="text-button" onClick={() => toggle(r)}>{r.status === 'closed' ? 'Reopen' : 'Close'}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
