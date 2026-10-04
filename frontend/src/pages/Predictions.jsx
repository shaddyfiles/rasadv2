import { useState } from 'react';
import { useApi, Link, Loading, Problem, fmt, ITEM, dateOf, shortName } from '../lib.jsx';

const pct = p => p >= 0.995 ? 'certain' : p < 0.005 ? 'none' : `${Math.round(p * 100)}%`;

function Chance({ p }) {
  const tone = p >= 0.5 ? 'short' : p >= 0.2 ? 'low' : 'ok';
  return (
    <span className={`chance chance-${tone}`}>
      <span className="chance-bar" aria-hidden="true"><span style={{ width: `${Math.max(2, p * 100)}%` }} /></span>
      <span className="chance-n">{pct(p)}</span>
    </span>
  );
}

function Shares({ rows }) {
  return (
    <dl className="shares">
      {rows.map(r => (
        <div key={r.feature}><dt>{r.feature}</dt><dd><span className="share-bar"><span style={{ width: `${Math.max(1, r.share * 100)}%` }} /></span>{Math.round(r.share * 100)}%</dd></div>
      ))}
    </dl>
  );
}

export default function Predictions() {
  const { data, error } = useApi('/predict');
  const [all, setAll] = useState(false);
  if (error) return <div className="page"><Problem error={error} /></div>;
  if (!data) return <div className="page"><h1>Predictions</h1><Loading what="Running 500 simulations per post and the road model" /></div>;

  const rows = data.stockout.rows.filter(r => all || r.p14 >= 0.05);
  const roads = [...data.roads.roads].sort((a, b) => Math.max(...b.days.map(d => d.p)) - Math.max(...a.days.map(d => d.p)));
  const days = roads[0]?.days.map(d => d.day) || [];
  const rs = data.roads.stats, dm = data.demand;
  const firstClose = roads.map(r => ({ r, d: r.days.find(x => x.p >= 0.5) })).filter(x => x.d && x.r.status !== 'closed');

  return (
    <div className="page">
      <h1>Predictions</h1>
      <p className="intro">What the models expect over the next one to two weeks, and how far to trust them. Figures update whenever usage, stock or roads change.</p>

      <section className="pred-section">
        <h2>Chance of running out</h2>
        <p className="note">Each post's next two weeks played out {data.stockout.simulations} times, with daily use drawn from the forecast range and loads already on the way counted. The run-out window covers the middle 80% of those simulations.</p>
        <div className="table-wrap">
          <table className="ledger">
            <thead><tr><th>Post</th><th>Item</th><th>Within 3 days</th><th>Within a week</th><th>Likely runs out</th></tr></thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.base_id + r.item}>
                  <td><Link to={`/bases/${r.base_id}`}>{shortName(r.base)}</Link></td>
                  <td>{ITEM[r.item]}</td>
                  <td><Chance p={r.p3} /></td>
                  <td><Chance p={r.p7} /></td>
                  <td>{r.window ? (r.window[0] === r.window[1] ? dateOf(r.window[0]) : `${dateOf(r.window[0])} to ${dateOf(r.window[1])}`) : <span className="quiet">Not within two weeks</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p><button type="button" className="text-button" onClick={() => setAll(!all)}>{all ? 'Show only items at risk' : `Show all ${data.stockout.rows.length} post and item pairs`}</button></p>
      </section>

      <section className="pred-section">
        <h2>Roads over the next week</h2>
        <p className="note">
          Chance of each road closing, from the weather forecast.
          {firstClose.length ? ` ${firstClose.slice(0, 3).map(x => `${x.r.name} from ${dateOf(x.d.day)}`).join(', ')}${firstClose.length > 3 ? ` and ${firstClose.length - 3} more` : ''} look likely to shut.` : ' No road looks likely to shut this week.'}
          {' '}The planner uses each road's highest chance over the next three days. <Link to="/roads">Edit roads</Link>.
        </p>
        <div className="table-wrap">
          <table className="ledger outlook">
            <thead><tr><th>Road</th>{days.map((d, i) => <th key={d} className="c">{i === 0 ? 'Today' : dateOf(d)}</th>)}</tr></thead>
            <tbody>
              {roads.map(r => (
                <tr key={r.id}>
                  <td>{r.name}{r.status === 'closed' && <span className="t-short"> (closed now)</span>}</td>
                  {r.days.map(d => (
                    <td key={d.day} className="c">
                      <span className="day-cell" style={{ '--p': d.p }} title={`${r.name}, ${dateOf(d.day)}: ${Math.round(d.p * 100)}% chance of closure, ${fmt(d.snow_cm)} cm snow forecast`}>{d.p < 0.05 ? '' : `${Math.round(d.p * 100)}`}</span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="note">Numbers are percentages; blank means under 5%.</p>
      </section>

      <section className="pred-section trust">
        <div>
          <h2>How far to trust the demand forecast</h2>
          <p className="note">Each model was trained without the last {dm.holdout_days} days and then asked to predict them. Error is the share of actual use it got wrong, weighted by weight carried.</p>
          <table className="ledger">
            <thead><tr><th>Model</th><th className="n">Error</th></tr></thead>
            <tbody>
              <tr><td><strong>Blend used by Rasad</strong></td><td className="n"><strong>{fmt(dm.by_model.ens * 100, 1)}%</strong></td></tr>
              <tr><td>{dm.engine === 'xgboost' ? 'XGBoost' : 'Gradient-boosted trees'} alone</td><td className="n">{fmt(dm.by_model.ml * 100, 1)}%</td></tr>
              <tr><td>Per-person regression alone</td><td className="n">{fmt(dm.by_model.lin * 100, 1)}%</td></tr>
              <tr><td>Last week's average (no model)</td><td className="n">{fmt(dm.by_model.naive * 100, 1)}%</td></tr>
            </tbody>
          </table>
          <p className="note">The boosted trees' own 10–90% range caught {fmt(dm.quantile_coverage * 100)}% of actual days, short of the 80% it should, so the range Rasad shows is reset from the blend's recent errors instead.</p>
          <h3 className="minor">What drives daily use</h3>
          <Shares rows={dm.importance} />
        </div>
        <div>
          <h2>How far to trust the road model</h2>
          <p className="note">Trained on {rs.trained_on_days} days of weather and recorded closures, then tested on the last {rs.holdout_days} days it had not seen.</p>
          <table className="ledger">
            <tbody>
              <tr><td>Ranks a closed day above an open day</td><td className="n"><strong>{rs.auc ? `${Math.round(rs.auc * 100)}% of the time` : '–'}</strong></td></tr>
              <tr><td>Squared error of its chances</td><td className="n">{rs.brier ? fmt(rs.brier, 3) : '–'}</td></tr>
              <tr><td>Same, guessing the usual closure rate</td><td className="n">{rs.brier_baseline ? fmt(rs.brier_baseline, 3) : '–'}</td></tr>
              <tr><td>Roads closed on an average day</td><td className="n">{fmt(rs.closure_rate * 100)}%</td></tr>
            </tbody>
          </table>
          <h3 className="minor">What closes a road</h3>
          <Shares rows={rs.importance} />
        </div>
      </section>
    </div>
  );
}
