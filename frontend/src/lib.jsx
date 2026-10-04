// Shared plumbing: API client, data hook, router, toasts, formatting.
import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { demoApi } from './demo.js';

// Set by the single-file demo build, which replays recorded API responses.
export const DEMO = typeof window !== 'undefined' && !!window.RASAD_DEMO;

/* ---------- API ---------- */
const key = () => { try { return localStorage.getItem('rasad.key') || ''; } catch { return ''; } };

export async function api(path, { method, body } = {}) {
  if (DEMO) return demoApi(path, { method, body });
  const headers = { 'Content-Type': 'application/json' };
  if (key()) headers['X-API-Key'] = key();
  let res;
  try {
    res = await fetch('/api' + path, { method: method || (body ? 'POST' : 'GET'), headers, body: body ? JSON.stringify(body) : undefined });
  } catch {
    throw new Error('The Rasad server is not responding. Check that it is running.');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.error || `The server returned ${res.status}.`);
  return data;
}

/* ---------- shared refresh + toast ---------- */
const Ctx = createContext(null);
export function AppProvider({ children }) {
  const [version, setVersion] = useState(0);
  const [toast, setToast] = useState(null);
  const bump = useCallback(() => setVersion(v => v + 1), []);
  const say = useCallback((text, error = false) => {
    setToast({ text, error });
    clearTimeout(window.__rasadToast);
    window.__rasadToast = setTimeout(() => setToast(null), 4000);
  }, []);
  return (
    <Ctx.Provider value={{ version, bump, say }}>
      {children}
      {toast && <div className={`toast${toast.error ? ' is-error' : ''}`} role="status">{toast.text}</div>}
    </Ctx.Provider>
  );
}
export const useApp = () => useContext(Ctx);

export function useApi(path) {
  const { version } = useApp();
  const [state, set] = useState({ data: null, error: null, loading: true });
  useEffect(() => {
    if (!path) { set({ data: null, error: null, loading: false }); return; }
    let live = true;
    set(s => ({ ...s, loading: true }));
    api(path).then(d => live && set({ data: d, error: null, loading: false }))
      .catch(e => live && set({ data: null, error: e.message, loading: false }));
    return () => { live = false; };
  }, [path, version]);
  return state;
}

/* ---------- router (history API; Flask serves index.html for every page path) ---------- */
// The demo keeps the current page in memory, since it runs inside a frame with no server behind it.
let demoPath = '/';
const currentPath = () => (DEMO ? demoPath : location.pathname);
export function navigate(to) {
  if (to === currentPath()) return;
  if (DEMO) demoPath = to; else history.pushState(null, '', to);
  dispatchEvent(new PopStateEvent('popstate'));
  window.scrollTo(0, 0);
}
export function usePath() {
  const [p, setP] = useState(currentPath);
  useEffect(() => {
    const f = () => setP(currentPath());
    addEventListener('popstate', f);
    return () => removeEventListener('popstate', f);
  }, []);
  return p;
}
export function Link({ to, children, ...rest }) {
  return (
    <a href={to} {...rest} onClick={e => {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
      e.preventDefault();
      navigate(to);
    }}>{children}</a>
  );
}

/* ---------- formatting ---------- */
export const fmt = (n, dp = 0) => (n === null || n === undefined || Number.isNaN(n)) ? '–' : Number(n).toLocaleString('en-IN', { maximumFractionDigits: dp, minimumFractionDigits: dp });
export const lasts = d => (d === null || d === undefined) ? 'over 60 days' : d < 1 ? 'under a day' : `${fmt(d, 1)} days`;
export const level = d => (d === null || d === undefined) ? 'ok' : d < 3 ? 'short' : d < 7 ? 'low' : 'ok';
export const shortName = name => name.split(' ').slice(-1)[0];
export const ITEM = { ration: 'Rations', fuel: 'Fuel', ammo: 'Ammunition', med: 'Medical stores', spares: 'Spares' };
const MANY = { ration: 'kg', fuel: 'litres', ammo: 'boxes', med: 'kits', spares: 'parts' };
const ONE = { ration: 'kg', fuel: 'litre', ammo: 'box', med: 'kit', spares: 'part' };
export const unit = (item, q = 2) => (Math.round(q) === 1 ? ONE[item] : MANY[item]);
export const qty = (item, q) => `${fmt(q)} ${unit(item, q)}`;
export const dateOf = iso => iso ? new Date(iso.length === 10 ? iso + 'T00:00:00' : iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : '–';
export const today = iso => (iso ? new Date(iso + 'T00:00:00') : new Date()).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
const WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'];
export const countWord = n => WORDS[n] || String(n);

/* ---------- small UI pieces ---------- */
export function Cover({ days }) {
  const l = level(days);
  return <span className={`cover cover-${l}`}><i aria-hidden="true" />{lasts(days)}</span>;
}
export function Loading({ what = 'Loading' }) { return <p className="quiet">{what}…</p>; }
export function Problem({ error }) { return <p className="problem">{error}</p>; }
