import { api, useApi, useApp, Link, Loading, Problem, ITEM, qty, dateOf, shortName } from '../lib.jsx';

export default function Movements() {
  const { bump, say } = useApp();
  const { data, error } = useApi('/shipments?all=1');
  if (error) return <div className="page"><Problem error={error} /></div>;
  if (!data) return <div className="page"><Loading /></div>;
  const moving = data.filter(s => s.status === 'in_transit'), done = data.filter(s => s.status !== 'in_transit');

  const deliver = async s => {
    try { await api(`/shipments/${s.id}/deliver`, { body: {} }); say(`${s.trip.vehicle} delivered. Stock added at ${s.trip.drops.map(d => shortName(d.base)).join(' and ')}.`); bump(); }
    catch (e) { say(e.message, true); }
  };
  const contents = t => t.drops.map(d => `${shortName(d.base)}: ${d.lines.map(l => `${qty(l.item, l.qty)} ${ITEM[l.item].toLowerCase()}`).join(', ')}`);

  return (
    <div className="page">
      <h1>Movements</h1>
      <p className="intro">Loads sent from a plan. When a load arrives, mark it delivered and the stock is added at each stop.</p>

      <h2>On the way</h2>
      {moving.length ? (
        <div className="table-wrap">
          <table className="ledger">
            <thead><tr><th>Load</th><th>Vehicle</th><th>Stops and contents</th><th>Due</th><th><span className="sr">Action</span></th></tr></thead>
            <tbody>
              {moving.map(s => (
                <tr key={s.id}>
                  <td>{s.id}</td>
                  <td>{s.trip.vehicle}<br /><small className="quiet">from {shortName(s.trip.from_name)}</small></td>
                  <td>{contents(s.trip).map((c, i) => <div key={i}>{c}</div>)}</td>
                  <td>{dateOf(s.eta)}</td>
                  <td className="row-action"><button type="button" className="button small" onClick={() => deliver(s)}>Mark delivered</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="quiet">Nothing is on the way. <Link to="/plan">Make a plan</Link> and send it.</p>}

      {done.length > 0 && <>
        <h2>Delivered</h2>
        <div className="table-wrap">
          <table className="ledger quiet-table">
            <thead><tr><th>Load</th><th>Vehicle</th><th>Stops and contents</th><th>Sent</th></tr></thead>
            <tbody>{done.map(s => <tr key={s.id}><td>{s.id}</td><td>{s.trip.vehicle}</td><td>{contents(s.trip).join('; ')}</td><td>{dateOf(s.created_at)}</td></tr>)}</tbody>
          </table>
        </div>
      </>}
    </div>
  );
}
