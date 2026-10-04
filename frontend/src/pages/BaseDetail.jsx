import { useState } from 'react';
import { api, useApi, useApp, Link, Cover, Loading, Problem, fmt, ITEM, unit, qty, dateOf } from '../lib.jsx';
import { ForecastChart } from '../Chart.jsx';

export default function BaseDetail({ id }) {
  const { bump, say } = useApp();
  const base = useApi(`/bases/${id}`);
  const all = useApi('/bases');
  const [item, setItem] = useState('fuel');
  const isPost = base.data?.kind === 'post';
  const fc = useApi(isPost ? `/forecast/${id}/${item}` : null);
  const [edit, setEdit] = useState(null);
  const [use, setUse] = useState({ item: 'fuel', qty: '', error: '' });
  const [strength, setStrength] = useState(null);

  if (base.error) return <div className="page"><p><Link to="/bases">All bases</Link></p><Problem error={base.error} /></div>;
  if (!base.data) return <div className="page"><Loading /></div>;
  const b = base.data;
  const depot = all.data?.find(x => x.id === b.depot_id);

  const saveStock = async it => {
    const q = Number(edit.value);
    if (edit.value === '' || Number.isNaN(q) || q < 0) { setEdit({ ...edit, error: 'Enter a quantity of 0 or more.' }); return; }
    try { await api(`/inventory/${b.id}/${it}`, { method: 'PUT', body: { qty: q } }); setEdit(null); say(`${ITEM[it]} at ${b.name} set to ${qty(it, q)}.`); bump(); }
    catch (e) { say(e.message, true); }
  };
  const recordUse = async e => {
    e.preventDefault();
    const q = Number(use.qty);
    if (use.qty === '' || Number.isNaN(q) || q <= 0) { setUse({ ...use, error: 'Enter how much was used today.' }); return; }
    try { await api('/consumption', { body: { base_id: b.id, item_id: use.item, qty: q } }); say(`Recorded ${qty(use.item, q)} of ${ITEM[use.item].toLowerCase()} used today. Forecasts will learn from it.`); setUse({ ...use, qty: '', error: '' }); bump(); }
    catch (err) { say(err.message, true); }
  };
  const saveStrength = async e => {
    e.preventDefault();
    const s = Number(strength);
    if (!Number.isInteger(s) || s < 0) { say('Troop strength must be a whole number.', true); return; }
    try { await api(`/bases/${b.id}`, { method: 'PATCH', body: { strength: s } }); setStrength(null); say(`Strength at ${b.name} set to ${s}. Forecasts updated.`); bump(); }
    catch (err) { say(err.message, true); }
  };

  const meta = b.kind === 'post'
    ? `${fmt(b.alt_m)} metres up, ${b.strength} troops, ${fmt(b.temp_c)} °C today. Supplied from ${depot ? depot.name : b.depot_id}.`
    : b.kind === 'depot' ? `${fmt(b.alt_m)} metres up. Cover here means how long this stock would last the posts it supplies.`
      : 'The rear base. Its stock is treated as unlimited.';

  return (
    <div className="page">
      <h1>{b.name}</h1>
      <p className="intro">{meta}</p>

      <div className="detail">
        <section>
          <h2>Stock</h2>
          <div className="table-wrap">
            <table className="ledger stock">
              <thead><tr><th>Item</th><th className="n">On hand</th><th className="n">Used a day</th><th>Lasts</th><th>Runs out</th><th className="n">On the way</th><th><span className="sr">Edit</span></th></tr></thead>
              <tbody>
                {b.inventory.map(r => (
                  <tr key={r.item} className={isPost && item === r.item ? 'is-current' : ''}>
                    <td>{isPost ? <button type="button" className="text-button" aria-pressed={item === r.item} onClick={() => setItem(r.item)}>{ITEM[r.item]}</button> : ITEM[r.item]}</td>
                    <td className="n">
                      {edit?.item === r.item ? (
                        <span className="inline-edit">
                          <input type="number" min="0" value={edit.value} autoFocus aria-label={`${ITEM[r.item]} on hand`} onChange={e => setEdit({ ...edit, value: e.target.value, error: '' })} onKeyDown={e => { if (e.key === 'Enter') saveStock(r.item); if (e.key === 'Escape') setEdit(null); }} />
                          {edit.error && <small className="t-short">{edit.error}</small>}
                        </span>
                      ) : r.qty === null ? 'Unlimited' : qty(r.item, r.qty)}
                    </td>
                    <td className="n">{r.per_day === null ? '–' : fmt(r.per_day, r.per_day < 10 ? 1 : 0)}</td>
                    <td>{b.kind === 'base' ? '–' : <Cover days={r.cover_days} />}</td>
                    <td>{r.runs_out ? dateOf(r.runs_out) : '–'}</td>
                    <td className="n">{r.inbound ? qty(r.item, r.inbound) : '–'}</td>
                    <td className="row-action">
                      {r.qty === null ? null : edit?.item === r.item
                        ? <><button type="button" className="button small" onClick={() => saveStock(r.item)}>Save</button> <button type="button" className="text-button" onClick={() => setEdit(null)}>Cancel</button></>
                        : <button type="button" className="text-button" onClick={() => setEdit({ item: r.item, value: String(Math.round(r.qty)) })}>Correct</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {isPost && (
            <div className="forecast">
              <h2>{ITEM[item]}: last month and the next two weeks</h2>
              {fc.data ? <>
                <ForecastChart history={fc.data.history} forecast={fc.data.forecast} unitLabel={unit(item)} />
                <p className="note">The dark line is what the post actually used. The dashed line is the forecast, with the shaded band covering the likely range (10th to 90th percentile). It comes from a {fc.data.engine === 'xgboost' ? 'XGBoost' : 'gradient-boosted tree'} model trained on all posts, using troop strength, temperature, altitude and operational tempo.</p>
              </> : <Loading what="Working out the forecast" />}
            </div>
          )}
        </section>

        {isPost && (
          <aside className="detail-side">
            <form onSubmit={recordUse} className="form" noValidate>
              <h2>Record today's usage</h2>
              <p className="note">Lowers the stock and teaches the forecast.</p>
              <label>Item
                <select value={use.item} onChange={e => setUse({ ...use, item: e.target.value })}>
                  {Object.entries(ITEM).map(([k, v]) => <option key={k} value={k}>{v} ({unit(k)})</option>)}
                </select>
              </label>
              <label>Quantity used
                <input type="number" min="0" step="any" value={use.qty} onChange={e => setUse({ ...use, qty: e.target.value, error: '' })} aria-invalid={!!use.error} />
              </label>
              {use.error && <p className="t-short field-error">{use.error}</p>}
              <button type="submit" className="button">Record usage</button>
            </form>

            <form onSubmit={saveStrength} className="form" noValidate>
              <h2>Troop strength</h2>
              <p className="note">Forecasts scale with the number of troops at the post.</p>
              <label>Troops at {b.name.split(' ').slice(-1)}
                <input type="number" min="0" step="1" value={strength ?? b.strength} onChange={e => setStrength(e.target.value)} />
              </label>
              <button type="submit" className="button secondary" disabled={strength === null || Number(strength) === b.strength}>Update strength</button>
            </form>
          </aside>
        )}
      </div>
    </div>
  );
}
