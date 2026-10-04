import { useApi, Link, navigate, Cover, Loading, Problem, shortName, countWord, today, lasts, dateOf } from '../lib.jsx';
import SectorMap from '../SectorMap.jsx';

const ICON = {
  bases: <path d="M4 20 V9 L12 4 L20 9 V20 Z M9 20 V14 H15 V20" />,
  predictions: <path d="M4 19 H20 M6 16 L10 11 L13 14 L19 6 M15 6 H19 V10" />,
  plan: <path d="M5 18 C9 18 8 12 12 12 S15 6 19 6 M5 18 m-2 0 a2 2 0 1 0 4 0 a2 2 0 1 0 -4 0 M19 6 m-2 0 a2 2 0 1 0 4 0 a2 2 0 1 0 -4 0" />,
  movements: <path d="M3 16 V8 H14 V16 M14 11 H18 L21 14 V16 H14 M7 18 m-2 0 a2 2 0 1 0 4 0 a2 2 0 1 0 -4 0 M17 18 m-2 0 a2 2 0 1 0 4 0 a2 2 0 1 0 -4 0" />,
  roads: <path d="M9 3 L5 21 M15 3 L19 21 M12 5 V8 M12 11 V14 M12 17 V20" />,
  assistant: <path d="M4 5 H20 V15 H11 L6 19 V15 H4 Z M8 9 H16 M8 12 H13" />,
};
const TILES = [
  ['/bases', 'bases', 'Bases', 'Stock, daily use and run-out dates for every post and depot'],
  ['/predictions', 'predictions', 'Predictions', 'Chance of running out and of each road closing this week'],
  ['/plan', 'plan', 'Resupply plan', 'Trucks and helicopters planned by GA and ant colony search'],
  ['/movements', 'movements', 'Movements', 'Loads on the way and delivery record'],
  ['/roads', 'roads', 'Roads', 'Road register, closures and engineer overrides'],
  ['/assistant', 'assistant', 'Ask Rasad', 'Questions and instructions in plain words'],
];

function headline(posts) {
  const short = posts.filter(p => p.worst_days !== null && p.worst_days < 3);
  if (!short.length) return 'No post runs out of anything in the next three days.';
  if (short.length === 1) {
    const p = short[0];
    return `${shortName(p.name)} runs out of ${p.worst_item.split(' (')[0].toLowerCase()} in ${lasts(p.worst_days)}.`;
  }
  return `${countWord(short.length)} posts run out of something within three days.`;
}

export default function Overview() {
  const map = useApi('/map');
  const ships = useApi('/shipments');
  const roads = useApi('/roads');
  const health = useApi('/health');
  if (map.error) return <div className="page"><Problem error={map.error} /></div>;
  if (!map.data) return <div className="page"><Loading /></div>;

  const sites = map.data.bases.features.map(f => f.properties);
  const posts = sites.filter(s => s.kind === 'post');
  const soon = sites.filter(s => s.kind !== 'base' && s.worst_days !== null && s.worst_days < 7).sort((a, b) => a.worst_days - b.worst_days);
  const watch = (roads.data || []).filter(r => r.status === 'closed' || r.risk >= 0.4);
  const week = soon.filter(s => s.worst_days >= 3 && s.kind === 'post');

  return (
    <div className="page">
      <section className="lede">
        <p className="dateline">Sector Himgiri · {today(health.data?.today)}</p>
        <h1>{headline(posts)}</h1>
        <p className="lede-text">
          {week.length ? `${week.map(s => shortName(s.name)).join(', ').replace(/, ([^,]*)$/, ' and $1')} will need supplies within the week. ` : ''}
          {watch.length ? `${watch.length === 1 ? watch[0].name + (watch[0].status === 'closed' ? ' is closed.' : ' may close.') : `${watch.length} roads are closed or likely to close.`}` : 'All roads are open.'}
        </p>
        <p className="lede-actions"><Link to="/plan" className="button bright">Plan resupply</Link><Link to="/predictions" className="button ghost">See the week's predictions</Link></p>
      </section>

      <section aria-labelledby="services">
        <h2 id="services" className="section-title">Services</h2>
        <ul className="tiles">
          {TILES.map(([to, icon, label, text]) => (
            <li key={to}>
              <Link to={to} className="tile">
                <svg viewBox="0 0 24 24" aria-hidden="true">{ICON[icon]}</svg>
                <span><strong>{label}</strong><small>{text}</small></span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <div className="overview">
        <section className="overview-map panel">
          <h2>Sector map: roads, weather and dangers</h2>
          <SectorMap map={map.data} height={600} onSelect={id => navigate(`/bases/${id}`)} />
        </section>

        <aside className="overview-side">
          <div className="panel">
          <h2>Needs supply soon</h2>
          {soon.length ? (
            <ol className="soon">
              {soon.map(s => (
                <li key={s.id}>
                  <Link to={`/bases/${s.id}`}>{s.name}</Link>
                  <span>{(s.worst_item || '').split(' (')[0]} <Cover days={s.worst_days} /></span>
                </li>
              ))}
            </ol>
          ) : <p className="quiet">Every post and depot has at least a week of stock.</p>}
          </div>

          <div className="panel">
          <h2>On the move</h2>
          {ships.data?.length ? (
            <ul className="plain">
              {ships.data.map(s => <li key={s.id}>{s.trip.vehicle} to {s.trip.drops.map(d => shortName(d.base)).join(' and ')}, due {dateOf(s.eta)}</li>)}
            </ul>
          ) : <p className="quiet">Nothing is on the road. <Link to="/plan">Make a plan</Link> to send loads.</p>}
          </div>

          <div className="panel">
          <h2>Roads to watch</h2>
          {watch.length ? (
            <ul className="plain">
              {watch.map(r => <li key={r.id}>{r.name}: {r.status === 'closed' ? <strong className="t-short">closed</strong> : `${Math.round(r.risk * 100)}% chance of closure`}</li>)}
            </ul>
          ) : <p className="quiet">All roads open with low risk.</p>}
          <p><Link to="/predictions" className="more">Road outlook for the week</Link></p>
          </div>
        </aside>
      </div>
    </div>
  );
}
