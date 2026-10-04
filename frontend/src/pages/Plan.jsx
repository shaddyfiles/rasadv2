import { useEffect, useState } from 'react';
import { api, useApi, useApp, Link, Loading, fmt, ITEM, qty, dateOf, shortName, countWord } from '../lib.jsx';
import MapView, { MapKey } from '../MapView.jsx';
import { Convergence } from '../Chart.jsx';

const WEIGHTS = [
  ['speed', 'Arrive sooner', 'Favour faster vehicles and shorter routes.'],
  ['safety', 'Avoid risky roads', 'Stay off roads likely to close or under observation.'],
  ['economy', 'Use fewer vehicles', 'Fill vehicles fuller and send fewer of them.'],
];

export default function Plan() {
  const { bump, say } = useApp();
  const map = useApi('/map');
  const [plan, setPlan] = useState(null);
  const [w, setW] = useState({ speed: 1, safety: 1, economy: 1 });
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState(null);

  useEffect(() => { api('/plan/latest').then(p => { if (p && p.status === 'proposed') { setPlan(p); setW(p.weights); } }).catch(() => {}); }, []);

  const run = async () => {
    setBusy(true);
    try { const p = await api('/plan', { body: { weights: w, seed: Math.floor(Math.random() * 1000) } }); setPlan({ ...p, status: 'proposed' }); setSel(p.trips[0] || null); }
    catch (e) { say(e.message, true); } finally { setBusy(false); }
  };
  const send = async () => {
    try {
      const r = await api(`/plan/${plan.id}/dispatch`, { body: {} });
      say(`${countWord(r.shipments.length)} ${r.shipments.length === 1 ? 'load is' : 'loads are'} on the way. Track them under Movements.`);
      setPlan({ ...plan, status: 'dispatched' }); bump();
    } catch (e) { say(e.message, true); }
  };

  const trucks = plan?.trips.filter(t => t.type === 'truck').length || 0;
  const helis = plan?.trips.filter(t => t.type === 'heli').length || 0;
  const held = plan ? Object.entries(plan.deferred) : [];

  return (
    <div className="page">
      <h1>Resupply plan</h1>
      <p className="intro">Rasad works out what each post will need from the forecasts, routes around closed roads and roads the weather model expects to close, then loads the trucks and helicopters. Say what matters most today and work out a plan.</p>

      <div className="plan">
        <section className="plan-main">
          <fieldset className="weights">
            <legend>What matters today</legend>
            {WEIGHTS.map(([k, label, help]) => (
              <label key={k}>
                <span className="w-head"><span>{label}</span><output>{['Ignore', 'A little', 'Normal', 'More', 'Much more', 'Most', 'Above all'][w[k] * 2]}</output></span>
                <input type="range" min="0" max="3" step="0.5" value={w[k]} onChange={e => setW({ ...w, [k]: Number(e.target.value) })} />
                <small>{help}</small>
              </label>
            ))}
            <button type="button" className="button" onClick={run} disabled={busy}>{busy ? 'Working it out…' : plan ? 'Work out a new plan' : 'Work out a plan'}</button>
          </fieldset>

          {plan && (
            <>
              <div className="plan-summary">
                <h2>{plan.trips.length ? `${countWord(plan.trips.length)} ${plan.trips.length === 1 ? 'trip' : 'trips'}: ${[trucks && `${trucks} by road`, helis && `${helis} by helicopter`].filter(Boolean).join(' and ')}` : 'Nothing needs to move today'}</h2>
                <p>{plan.trips.length ? `This plan scores ${fmt(plan.gain * 100)}% better than sending one vehicle per post from its own depot.` : 'Every post has enough stock until tomorrow’s plan.'}
                  {held.length ? ` Held for tomorrow because there is time: ${held.map(([b, it]) => `${Object.keys(it).map(i => ITEM[i].toLowerCase()).join(' and ')} for ${shortName(b)}`).join('; ')}.` : ''}</p>
                {plan.status === 'proposed' && plan.trips.length > 0 && <button type="button" className="button" onClick={send}>Send all trips</button>}
                {plan.status === 'dispatched' && <p className="t-ok">Sent. <Link to="/movements">Follow the loads</Link>.</p>}
              </div>

              <ol className="trips">
                {plan.trips.map(t => (
                  <li key={t.id} className={sel?.id === t.id ? 'is-current' : ''}>
                    <button type="button" className="trip" onClick={() => setSel(t)} aria-pressed={sel?.id === t.id}>
                      <span className="trip-head">
                        <strong>{t.vehicle}</strong>
                        {t.priority === 'flash' && <em className="urgent">Urgent</em>}
                        <span className="trip-fill">{t.fill_pct}% loaded</span>
                      </span>
                      <span className="trip-route">From {shortName(t.from_name)} {t.type === 'heli' ? 'by air' : `by ${t.route}`}</span>
                      <span className="drops">
                        {t.drops.map(d => <span key={d.base_id}><b>{shortName(d.base)}</b>, {dateOf(d.eta)}: {d.lines.map(l => `${qty(l.item, l.qty)} ${ITEM[l.item].toLowerCase()}`).join(', ')}</span>)}
                      </span>
                      <span className="why">{t.why}</span>
                    </button>
                  </li>
                ))}
              </ol>

              <details className="how">
                <summary>How this plan was found</summary>
                <p>A genetic algorithm tried {plan.convergence.length - 1} generations of {plan.lots} supply loads across {plan.vehicles_available} free vehicles, starting from the simple rule of one vehicle per post. Ant colony search picked each road route. Lower is better.</p>
                <Convergence values={plan.convergence} baseline={plan.baseline.cost} />
              </details>
            </>
          )}
          {!plan && !busy && <p className="quiet">No plan yet. Set the priorities above and work one out.</p>}
        </section>

        <aside className="plan-map">
          {map.data ? <MapView data={map.data} height={540} trip={sel} layers={{ closure: true, dangers: true, cover: false }} /> : <Loading />}
          <MapKey layers={{ closure: true, dangers: true }} />
          <p className="note">Percentages are each road's highest chance of closing over the next 3 days, which is what the planner uses. {sel ? `Showing ${sel.vehicle}${sel.type === 'heli' ? ' (dashed line is the flight)' : ''}. Pick another trip to see its route.` : 'Pick a trip to see its route.'}</p>
        </aside>
      </div>
    </div>
  );
}
