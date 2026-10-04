import { useEffect, useRef, useState } from 'react';
import { api, useApi, useApp, Link } from '../lib.jsx';

const TRY = ['Which posts are short?', 'Status of Trishul', 'Fuel forecast for Garud', 'Close Tangla road', 'Set fuel at Trishul to 500', 'Used 80 L of fuel at Vajra', 'Plan resupply', 'Dispatch'];

export default function Assistant() {
  const { bump, say } = useApp();
  const health = useApi('/health');
  const [log, setLog] = useState([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [brief, setBrief] = useState(null);
  const end = useRef(null);
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }); }, [log]);
  const online = health.data?.llm.online;

  const send = async q => {
    q = (q ?? text).trim();
    if (!q) return;
    setText(''); setBusy(true);
    const history = log.flatMap(m => m.role === 'you' ? [{ role: 'user', content: m.text }] : [{ role: 'assistant', content: m.text }]).slice(-6);
    setLog(l => [...l, { role: 'you', text: q }]);
    try {
      const r = await api('/command', { body: { text: q, history } });
      setLog(l => [...l, { role: 'rasad', text: r.reply, actions: r.actions.map(a => ({ ...a, state: 'waiting' })), mode: r.mode }]);
      if (r.tools.includes('plan_resupply')) bump();
    } catch (e) {
      setLog(l => [...l, { role: 'rasad', text: e.message, actions: [] }]);
    } finally { setBusy(false); }
  };
  const decide = async (mi, ai, yes) => {
    const a = log[mi].actions[ai];
    const mark = state => setLog(l => l.map((m, i) => i !== mi ? m : { ...m, actions: m.actions.map((x, j) => j !== ai ? x : { ...x, state }) }));
    if (!yes) { mark('dismissed'); return; }
    try { const r = await api('/command/execute', { body: { action: a } }); mark('done'); say(`Done: ${r.done}.`); bump(); }
    catch (e) { say(e.message, true); }
  };
  const getBrief = async () => { try { setBrief(await api('/alerts/brief', { body: {} })); } catch (e) { say(e.message, true); } };

  return (
    <div className="page">
      <h1>Ask Rasad</h1>
      <p className="intro">Ask about stock, routes or the plan, or give an instruction in plain words. Nothing changes until you confirm it.</p>
      <div className="ask">
        <section className="conversation" aria-live="polite">
          {log.length === 0 && (
            <div className="try">
              <p>Some things you can type:</p>
              <ul>{TRY.map(t => <li key={t}><button type="button" className="text-button" onClick={() => send(t)}>{t}</button></li>)}</ul>
            </div>
          )}
          {log.map((m, i) => (
            <div key={i} className={`turn turn-${m.role}`}>
              <p className="who">{m.role === 'you' ? 'You' : 'Rasad'}</p>
              <p className="said">{m.text}</p>
              {m.actions?.map((a, j) => (
                <div key={j} className="confirm">
                  <span>{a.label}</span>
                  {a.state === 'waiting' && <span className="confirm-buttons"><button type="button" className="button small" onClick={() => decide(i, j, true)}>Confirm</button><button type="button" className="text-button" onClick={() => decide(i, j, false)}>Not now</button></span>}
                  {a.state === 'done' && <span className="t-ok">Done</span>}
                  {a.state === 'dismissed' && <span className="quiet">Left unchanged</span>}
                </div>
              ))}
            </div>
          ))}
          <div ref={end} />
          <form className="composer" onSubmit={e => { e.preventDefault(); send(); }}>
            <label htmlFor="ask" className="sr">Your question or instruction</label>
            <input id="ask" value={text} onChange={e => setText(e.target.value)} placeholder="For example: close Tangla road" autoComplete="off" />
            <button type="submit" className="button" disabled={busy || !text.trim()}>{busy ? 'Thinking…' : 'Send'}</button>
          </form>
        </section>

        <aside className="ask-side">
          <h2>Briefing</h2>
          <p className="note">A short summary of today's alerts with one recommended action.</p>
          {brief ? <p className="brief">{brief.text}</p> : null}
          <button type="button" className="button secondary" onClick={getBrief}>{brief ? 'Write it again' : 'Write a briefing'}</button>
          <h2>About the assistant</h2>
          <p className="note">{online
            ? `Answers come from ${health.data.llm.model}, which reads the live data through Rasad's tools.`
            : 'No language model is connected, so Rasad understands a fixed set of phrasings. Connect Qwen3-8B to ask in your own words (see the README).'}</p>
          <p className="note">See also <Link to="/plan">the resupply plan</Link> and <Link to="/roads">the road network</Link>.</p>
        </aside>
      </div>
    </div>
  );
}
