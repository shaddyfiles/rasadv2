import { useState } from 'react';
import { api, useApi, useApp, Loading, Problem, fmt } from '../lib.jsx';

const pct = n => `${fmt(n, 1)}`;

function Row({ s }) {
  const r = s.result;
  const lost = r.old_plan.trips_lost;
  const helped = r.old_plan.expected_stockouts - r.after.expected_stockouts;
  return (
    <tr>
      <th scope="row">{s.label}<small>{r.changes.length ? r.changes.join('; ') : 'No disruption'}</small><small className={'verdict v-' + r.verdict.id}>{r.verdict.text}</small></th>
      <td className="num">{pct(r.nothing.expected_stockouts)}</td>
      <td className="num">{pct(r.old_plan.expected_stockouts)}<small>{lost ? `${lost} of ${lost + r.old_plan.trips_kept} loads cannot run` : 'every load can still run'}</small></td>
      <td className="num"><strong>{pct(r.after.expected_stockouts)}</strong>{helped > 0.05 && <small>{pct(helped)} fewer than the old plan</small>}</td>
      <td>{r.plan.trucks} truck{r.plan.trucks === 1 ? '' : 's'}, {r.plan.helicopters} helicopter{r.plan.helicopters === 1 ? '' : 's'}, {fmt(r.plan.tonnes, 1)} t
        {(r.plan.held > 0 || r.plan.late > 0) && <small>{r.plan.held ? `${r.plan.held} held back` : ''}{r.plan.held && r.plan.late ? ', ' : ''}{r.plan.late ? `${r.plan.late} late` : ''}</small>}</td>
    </tr>
  );
}

export default function WhatIf() {
  const { say } = useApp();
  const list = useApi('/whatif');
  const [done, setDone] = useState({});
  const [busy, setBusy] = useState(null);

  const run = async s => {
    setBusy(s.id);
    try { const result = await api('/whatif', { body: { scenario: s.id } }); setDone(d => ({ ...d, [s.id]: { ...s, result } })); }
    catch (e) { say(e.message, true); } finally { setBusy(null); }
  };
  const runAll = async () => { for (const s of list.data) await run(s); };

  if (list.error) return <div className="page"><h1>What if</h1><Problem error={list.error} /></div>;
  if (!list.data) return <div className="page"><h1>What if</h1><Loading /></div>;
  const rows = list.data.filter(s => done[s.id]).map(s => done[s.id]);

  return (
    <div className="page">
      <h1>What if</h1>
      <p className="intro">Pick a disruption. Rasad closes the road, grounds the helicopters or raises a post&rsquo;s strength on a copy of the sector, then plans again and plays the next week out 500 times. Nothing here changes your real stock, roads or plans.</p>

      <section className="panel">
        <h2>Choose a disruption</h2>
        <div className="scen-list">
          {list.data.map(s => (
            <button key={s.id} type="button" className={'scen' + (done[s.id] ? ' scen-done' : '')} onClick={() => run(s)} disabled={busy !== null}>
              <strong>{s.label}</strong>
              <span>{s.text}</span>
              <em>{busy === s.id ? 'Working it out…' : done[s.id] ? 'Run again' : 'Run this'}</em>
            </button>
          ))}
        </div>
        <div><button type="button" className="button" onClick={runAll} disabled={busy !== null}>{busy ? 'Working it out…' : 'Run all five'}</button></div>
      </section>

      {rows.length > 0 && (
        <section className="panel">
          <h2>What each disruption does</h2>
          <p className="quiet">Expected stock-outs in the next 7 days, counted across every post and supply item (lower is better).</p>
          <div className="table-wrap">
            <table className="register whatif">
              <thead><tr><th scope="col">Disruption</th><th scope="col">If nothing is sent</th><th scope="col">The plan you already had</th><th scope="col">A new plan</th><th scope="col">The new plan</th></tr></thead>
              <tbody>{rows.map(s => <Row key={s.id} s={s} />)}</tbody>
            </table>
          </div>
          <p className="quiet">&ldquo;The plan you already had&rdquo; is the plan made for today&rsquo;s sector. Loads that need a closed road or a grounded helicopter drop out. &ldquo;A new plan&rdquo; is Rasad planning again for the disrupted sector.</p>
        </section>
      )}
    </div>
  );
}
