import { useApi, Link, Cover, Loading, Problem, fmt } from '../lib.jsx';

const KIND = { post: 'Post', depot: 'Forward depot', base: 'Rear base' };

export default function Bases() {
  const { data, error } = useApi('/bases');
  if (error) return <div className="page"><Problem error={error} /></div>;
  if (!data) return <div className="page"><Loading /></div>;
  const names = Object.fromEntries(data.map(b => [b.id, b.name]));
  const rows = [...data].sort((a, b) => (a.kind === 'base') - (b.kind === 'base') || (a.worst_days ?? 999) - (b.worst_days ?? 999));
  return (
    <div className="page">
      <h1>Bases</h1>
      <p className="intro">Every post and depot in the sector, shortest stock first. Cover is how long the scarcest item lasts at forecast demand, counting loads already on the way.</p>
      <div className="table-wrap">
        <table className="ledger">
          <thead><tr><th>Base</th><th>Type</th><th className="n">Troops</th><th className="n">Height</th><th>Shortest cover</th><th>Supplied from</th></tr></thead>
          <tbody>
            {rows.map(b => (
              <tr key={b.id}>
                <td><Link to={`/bases/${b.id}`}>{b.name}</Link></td>
                <td>{KIND[b.kind]}</td>
                <td className="n">{b.kind === 'post' ? fmt(b.strength) : '–'}</td>
                <td className="n">{fmt(b.alt_m)} m</td>
                <td>{b.kind === 'base' ? 'Unlimited' : <><Cover days={b.worst_days} />{b.worst_item ? <span className="quiet"> of {b.worst_item.split(' (')[0].toLowerCase()}</span> : null}</>}</td>
                <td>{b.depot_id ? names[b.depot_id] : '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
