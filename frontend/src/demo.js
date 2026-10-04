// Demo mode: replays responses recorded from the real API (frontend/demo/capture.py), so the
// website runs as a single file with no server. Planning and dispatch switch between recorded
// states; other changes are refused with a clear message.

const D = () => window.RASAD_DEMO;
const s = { plan: null, variant: null, dispatched: null };
const wait = ms => new Promise(r => setTimeout(r, ms));
const READ_ONLY = 'This demo replays recorded data, so changes are not saved. Run the full app to make this change.';

const NAMES = ['trishul', 'hima', 'kesari', 'garud', 'vajra', 'agni', 'dhruv', 'neel', 'shakti', 'tangla', 'zarla'];
const norm = t => t.toLowerCase().replace(/[^a-z0-9% ]+/g, ' ').replace(/\s+/g, ' ').trim();

function command(text) {
  const cmds = D().commands, q = norm(text), qs = new Set(q.split(' '));
  let best = null, score = 0;
  const names = [...qs].filter(w => NAMES.includes(w));
  for (const k of Object.keys(cmds)) {
    const ks = norm(k).split(' ');
    if (!names.every(n => ks.includes(n))) continue;   // never answer about Garud when asked about Vajra
    const hit = ks.filter(w => qs.has(w)).length;
    const sc = hit / new Set([...ks, ...qs]).size;
    if (norm(k) === q) { best = k; score = 1; break; }
    if (sc > score) { best = k; score = sc; }
  }
  if (best && score >= 0.5) return cmds[best];
  return {
    reply: `In this demo Rasad answers a fixed set of recorded questions, such as "${Object.keys(cmds).slice(0, 3).join('", "')}". In the full app, connect Qwen3-8B to ask in your own words.`,
    actions: [], tools: [], mode: 'demo',
  };
}

function pickVariant(w) {
  const order = ['speed', 'safety', 'economy'];
  const top = Math.max(...order.map(k => w[k]));
  if (order.every(k => w[k] === top)) return 'normal';
  return order.reduce((a, k) => (w[k] > w[a] ? k : a), 'speed');
}

export async function demoApi(path, { method, body } = {}) {
  const d = D();
  const verb = method || (body ? 'POST' : 'GET');
  if (verb === 'GET') {
    await wait(60);
    if (path === '/plan/latest') return s.plan;
    if (path === '/whatif') return d.whatif.list;
    if (path.startsWith('/forecast/')) {
      if (d.forecasts[path]) return d.forecasts[path];
      throw new Error('Forecasts are shown for forward posts only.');
    }
    const after = s.dispatched && d.plans[s.dispatched].after;
    const hit = (after && after[path]) || d.state[path];
    if (hit !== undefined) return hit;
    throw new Error('That page is not part of the recorded demo.');
  }
  if (path === '/plan') {
    await wait(900);
    if (s.dispatched) throw new Error('The demo records one plan being sent. Reload the page to start again.');
    s.variant = pickVariant(body.weights);
    s.plan = { ...d.plans[s.variant].plan };
    return s.plan;
  }
  if (/^\/plan\/\d+\/dispatch$/.test(path) && s.variant) {
    await wait(300);
    s.dispatched = s.variant;
    s.plan = { ...s.plan, status: 'dispatched' };
    return d.plans[s.variant].dispatch;
  }
  if (path === '/whatif') {
    await wait(700);
    const r = d.whatif.results[body.scenario];
    if (r) return r;
    throw new Error('The demo has recorded results for the five ready-made scenarios only.');
  }
  if (path === '/command') { await wait(350); return command(body.text); }
  if (path === '/alerts/brief') { await wait(350); return d.brief; }
  if (path === '/predict/roads/refresh') { await wait(200); return { ok: true }; }
  await wait(150);
  throw new Error(READ_ONLY);
}
