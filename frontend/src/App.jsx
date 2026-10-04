import { useEffect, useState } from 'react';
import { AppProvider, Link, usePath, useApi, useApp, navigate, DEMO } from './lib.jsx';
import Overview from './pages/Overview.jsx';
import Bases from './pages/Bases.jsx';
import BaseDetail from './pages/BaseDetail.jsx';
import Plan from './pages/Plan.jsx';
import Movements from './pages/Movements.jsx';
import Roads from './pages/Roads.jsx';
import Assistant from './pages/Assistant.jsx';
import Predictions from './pages/Predictions.jsx';

export const NAV = [['/', 'Home'], ['/bases', 'Bases'], ['/predictions', 'Predictions'], ['/plan', 'Resupply plan'], ['/movements', 'Movements'], ['/roads', 'Roads'], ['/assistant', 'Ask Rasad']];
const TITLES = Object.fromEntries(NAV);

function route(path) {
  const m = path.match(/^\/bases\/([\w-]+)\/?$/);
  if (m) return <BaseDetail id={m[1]} />;
  switch (path.replace(/\/$/, '') || '/') {
    case '/': return <Overview />;
    case '/bases': return <Bases />;
    case '/plan': return <Plan />;
    case '/movements': return <Movements />;
    case '/roads': return <Roads />;
    case '/assistant': return <Assistant />;
    case '/predictions': return <Predictions />;
    default: return <div className="page"><h1>Page not found</h1><p>There is no page at {path}. <Link to="/">Go to the home page</Link>.</p></div>;
  }
}

/* ---------- reading preferences: text size and contrast (GIGW accessibility controls) ---------- */
const SIZES = [['small', 'A-', 'Smaller text'], ['normal', 'A', 'Normal text size'], ['large', 'A+', 'Larger text']];
const read = (k, d) => { try { return localStorage.getItem(k) || d; } catch { return d; } };
const keep = (k, v) => { try { localStorage.setItem(k, v); } catch { /* storage blocked: still works for this visit */ } };

function useReading() {
  const [size, setSize] = useState(() => read('rasad.size', 'normal'));
  const [contrast, setContrast] = useState(() => read('rasad.contrast', 'normal'));
  useEffect(() => { document.documentElement.dataset.size = size; keep('rasad.size', size); }, [size]);
  useEffect(() => { document.documentElement.dataset.contrast = contrast; keep('rasad.contrast', contrast); }, [contrast]);
  return { size, setSize, contrast, setContrast };
}

function Emblem() {
  // Rasad's own mark: a supply route climbing to a post below a ridge. Not a government or Army emblem.
  return (
    <svg className="mark" viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="32" cy="32" r="30" className="mark-ring" />
      <path d="M8 44 L22 26 L30 35 L40 20 L56 44 Z" className="mark-hill" />
      <path d="M14 50 C24 46 26 40 33 39 S44 33 46 27" className="mark-route" />
      <circle cx="46" cy="27" r="3.4" className="mark-post" />
    </svg>
  );
}

function Search() {
  const bases = useApi('/bases');
  const roads = useApi('/roads');
  const { say } = useApp();
  const [q, setQ] = useState('');
  const go = e => {
    e.preventDefault();
    const t = q.trim().toLowerCase();
    if (!t) return;
    const b = bases.data?.find(x => x.name.toLowerCase().includes(t) || x.id.toLowerCase() === t);
    const r = roads.data?.find(x => x.name.toLowerCase().includes(t));
    const page = NAV.find(([, label]) => label.toLowerCase().includes(t));
    if (b) navigate(`/bases/${b.id}`);
    else if (r) navigate('/roads');
    else if (/fuel|ration|ammo|ammunition|medic|spare|run out|stock/.test(t)) navigate('/predictions');
    else if (page) navigate(page[0]);
    else { say(`Nothing found for "${q.trim()}". Try a post, depot or road name.`, true); return; }
    setQ('');
  };
  return (
    <form className="search" role="search" onSubmit={go}>
      <label htmlFor="site-search" className="sr">Search bases, roads and pages</label>
      <input id="site-search" list="search-list" value={q} onChange={e => setQ(e.target.value)} placeholder="Search a post, depot or road" autoComplete="off" />
      <datalist id="search-list">
        {bases.data?.map(b => <option key={b.id} value={b.name} />)}
        {roads.data?.map(r => <option key={r.id} value={r.name} />)}
      </datalist>
      <button type="submit" className="search-go" aria-label="Search">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="M15.5 15.5 L21 21" /></svg>
      </button>
    </form>
  );
}

function Ticker() {
  const alerts = useApi('/alerts');
  const items = alerts.data || [];
  if (!items.length) return null;
  const line = items.map((a, i) => (
    <span key={i} className={`tick tick-${a.level}`}>
      {a.base_id ? <Link to={`/bases/${a.base_id}`}>{a.text}</Link> : <Link to="/roads">{a.text}</Link>}
    </span>
  ));
  return (
    <div className="ticker" role="region" aria-label="Latest alerts">
      <div className="wrap ticker-in">
        <span className="ticker-label">Alerts</span>
        <div className="ticker-track" tabIndex={0}>
          <div className="ticker-run">{line}<span aria-hidden="true" className="ticker-copy">{line}</span></div>
        </div>
      </div>
    </div>
  );
}

function Crumbs({ path }) {
  const bases = useApi('/bases');
  if (path === '/') return null;
  const parts = [['/', 'Home']];
  const m = path.match(/^\/bases\/([\w-]+)/);
  if (m) {
    parts.push(['/bases', 'Bases']);
    parts.push([null, bases.data?.find(b => b.id === m[1])?.name || m[1]]);
  } else parts.push([null, TITLES[path.replace(/\/$/, '')] || 'Page not found']);
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      <ol className="wrap">
        {parts.map(([to, label], i) => <li key={i}>{to ? <Link to={to}>{label}</Link> : <span aria-current="page">{label}</span>}</li>)}
      </ol>
    </nav>
  );
}

function Shell() {
  const path = usePath();
  const health = useApi('/health');
  const reading = useReading();
  const section = '/' + (path.split('/')[1] || '');
  useEffect(() => { document.title = `${TITLES[section] || 'Base'} | Rasad`; }, [section]);
  const h = health.data;
  const updated = h?.today ? new Date(h.today + 'T00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'long', year: 'numeric' }) : null;

  return (
    <>
      <div className="strip">
        <div className="wrap strip-in">
          <p className="strip-note"><span lang="hi">रसद</span> Rasad · Smart India Hackathon prototype, PS 26251</p>
          <div className="strip-tools">
            <a href="#main" className="strip-link" onClick={e => { e.preventDefault(); document.getElementById('main')?.focus(); }}>Skip to main content</a>
            <span className="strip-group" role="group" aria-label="Text size">
              {SIZES.map(([k, label, name]) => (
                <button key={k} type="button" className="strip-btn" aria-pressed={reading.size === k} aria-label={name} title={name} onClick={() => reading.setSize(k)}>{label}</button>
              ))}
            </span>
            <button type="button" className="strip-btn contrast" aria-pressed={reading.contrast === 'high'} title="High contrast" onClick={() => reading.setContrast(reading.contrast === 'high' ? 'normal' : 'high')}>
              <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.5" /><path d="M8 1.5 A6.5 6.5 0 0 1 8 14.5 Z" /></svg>
              <span>{reading.contrast === 'high' ? 'Normal contrast' : 'High contrast'}</span>
            </button>
          </div>
        </div>
      </div>

      <header className="portal-head">
        <div className="wrap head-in">
          <Link to="/" className="brand" aria-label="Rasad home">
            <Emblem />
            <span className="brand-text">
              <span className="brand-hi" lang="hi">रसद</span>
              <span className="brand-en">Rasad</span>
              <span className="brand-sub">Predictive Logistics &amp; Forward Supply Chain</span>
            </span>
          </Link>
          <Search />
        </div>
      </header>
      <div className="tricolour" aria-hidden="true"><span /><span /><span /></div>

      <nav className="mainnav" aria-label="Main">
        <div className="wrap">
          <ul>
            {NAV.map(([to, label]) => (
              <li key={to}>
                <Link to={to} aria-current={section === to ? 'page' : undefined}>
                  {to === '/' && <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 9.5 L10 3.5 L17 9.5 V17 H12 V12 H8 V17 H3 Z" /></svg>}
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </nav>
      <Ticker />
      {DEMO && <p className="demo-note"><span className="wrap">Demo with data recorded from the running app. Planning, sending a plan and the example questions work; other changes are not saved.</span></p>}
      <Crumbs path={path} />

      <main id="main" tabIndex={-1}><div className="wrap">{route(path)}</div></main>

      <footer className="portal-foot">
        <div className="wrap foot-cols">
          <section>
            <h2>Pages</h2>
            <ul>{NAV.map(([to, label]) => <li key={to}><Link to={to}>{label}</Link></li>)}</ul>
          </section>
          <section>
            <h2>Models in use</h2>
            <ul>
              <li>Demand: {h?.forecast_engine === 'xgboost' ? 'XGBoost' : 'gradient-boosted trees'} blended with a per-person regression</li>
              <li>Road closures: weather-driven classifier</li>
              <li>Stock-out risk: 500 Monte Carlo runs per post</li>
              <li>Planning: genetic algorithm with ant colony routing</li>
              <li>Assistant: {h?.llm.online ? `${h.llm.model}, connected` : 'Qwen3-8B when connected, built-in parser now'}</li>
            </ul>
          </section>
          <section>
            <h2>About this prototype</h2>
            <p>Rasad forecasts what each forward post will need, predicts which roads will close, and plans trucks and helicopters to get supplies through. Built for Smart India Hackathon problem statement 26251 (Ministry of Defence).</p>
            <p>Data stored in {h?.db === 'postgis' ? 'PostgreSQL with PostGIS' : 'SQLite (development)'}.</p>
          </section>
        </div>
        <div className="foot-base">
          <div className="wrap foot-base-in">
            <p>Sector Himgiri and all figures are synthetic, for demonstration only. This is not an official Government of India or Indian Army website.</p>
            {updated && <p>Last reviewed and updated on {updated}</p>}
          </div>
        </div>
      </footer>
    </>
  );
}

export default function App() {
  return <AppProvider><Shell /></AppProvider>;
}
