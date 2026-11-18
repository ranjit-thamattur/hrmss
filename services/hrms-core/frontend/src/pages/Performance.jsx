import { useState } from 'react';
import { api, fmtDate, label, money, useAction, useApp, useData } from '../lib.jsx';
import { Badge, Button, Card, Field, Modal, PageHeader, Select, Table, Tabs } from '../ui.jsx';

export default function Performance() {
  const { can } = useApp();
  const { data: cycles, reload } = useData('/performance/cycles');
  const [cid, setCid] = useState(null);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: '', opens_on: '', closes_on: '' });
  const [run, busy] = useAction();
  const cycle = cycles?.find((c) => c.id === cid) || cycles?.[0];
  return (
    <div className="stack">
      <PageHeader title="Performance" sub="Self-review, manager rating, HR calibration, then increments with GM sign-off." actions={can('performance.manage') && <Button variant="primary" onClick={() => setOpen(true)}>Launch review cycle</Button>} />
      <Card pad={false}>
        <Table rows={cycles} onRow={(c) => setCid(c.id)} rowClass={(c) => (c.id === cycle?.id ? 'row-on' : '')} cols={[{ key: 'name', label: 'Cycle' }, { label: 'Opens', render: (c) => fmtDate(c.opens_on) },
          { label: 'Closes', render: (c) => fmtDate(c.closes_on) }, { key: 'total', label: 'Reviews', align: 'right' },
          { label: 'Progress', render: (c) => Object.entries(c.progress || {}).map(([k, v]) => `${label(k)} ${v}`).join(' · ') }]} empty="No review cycles yet" />
      </Card>
      {cycle && <Cycle key={cycle.id} cycle={cycle} />}
      <Modal open={open} title="Launch review cycle" onClose={() => setOpen(false)} footer={<Button variant="primary" busy={busy} onClick={async () => {
        if (await run(() => api.post('/performance/cycles', f), 'Cycle launched; staff notified')) { setOpen(false); reload(); }
      }}>Launch</Button>}>
        <Field label="Name"><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="FY 2026-27 annual review" /></Field>
        <div className="grid g2">
          <Field label="Opens"><input className="input" type="date" value={f.opens_on} onChange={(e) => setF({ ...f, opens_on: e.target.value })} /></Field>
          <Field label="Closes"><input className="input" type="date" value={f.closes_on} onChange={(e) => setF({ ...f, closes_on: e.target.value })} /></Field>
        </div>
      </Modal>
    </div>
  );
}

function Cycle({ cycle }) {
  const { can } = useApp();
  const [tab, setTab] = useState('reviews');
  return (
    <>
      <Tabs tabs={[{ id: 'reviews', label: 'Reviews' }, ...(can('performance.manage') ? [{ id: 'inc', label: 'Increments' }] : [])]} value={tab} onChange={setTab} />
      {tab === 'reviews' ? <Reviews cycle={cycle} /> : <Increments cycle={cycle} />}
    </>
  );
}

const RATINGS = [1, 2, 3, 4, 5].map((n) => ({ value: n, label: `${n} · ${['Below', 'Needs work', 'Meets', 'Exceeds', 'Outstanding'][n - 1]}` }));

function Reviews({ cycle }) {
  const { can } = useApp();
  const { data, reload } = useData(`/performance/cycles/${cycle.id}/reviews`);
  const [r, setR] = useState(null);
  const [run, busy] = useAction();
  const save = async (body) => { if (await run(() => api.put(`/performance/reviews/${r.id}`, body), 'Review saved')) { setR(null); reload(); } };
  return (
    <Card pad={false}>
      <Table rows={data} onRow={(x) => setR({ ...x })} cols={[{ label: 'Employee', render: (x) => `${x.employee.code} ${x.employee.name}` }, { key: 'employee.department', label: 'Department', render: (x) => x.employee.department },
        { key: 'self_rating', label: 'Self', align: 'right' }, { key: 'manager_rating', label: 'Manager', align: 'right' }, { key: 'final_rating', label: 'Final', align: 'right' },
        { label: 'Status', render: (x) => <Badge value={x.status}>{label(x.status)}</Badge> }]} />
      <Modal open={!!r} title={r ? `Review · ${r.employee.name}` : ''} onClose={() => setR(null)} footer={r && <>
        <Button busy={busy} disabled={!r.manager_rating} onClick={() => save({ manager_rating: Number(r.manager_rating), manager_comment: r.manager_comment })}>Save manager rating</Button>
        {can('performance.manage') && <Button variant="primary" busy={busy} disabled={!r.final_rating} onClick={() => save({ final_rating: Number(r.final_rating) })}>Save final (calibrated)</Button>}</>}>
        {r && (
          <>
            <h4>Key result areas</h4>
            <ul className="small">{r.kras.map((k) => <li key={k}>{k}{r.self_ratings?.[k] ? ` — self ${r.self_ratings[k]}` : ''}</li>)}</ul>
            <Field label="Manager rating"><Select value={r.manager_rating ?? ''} onChange={(v) => setR({ ...r, manager_rating: v })} options={RATINGS} placeholder="—" /></Field>
            <Field label="Manager comment"><textarea className="input" rows={2} value={r.manager_comment || ''} onChange={(e) => setR({ ...r, manager_comment: e.target.value })} /></Field>
            {can('performance.manage') && <Field label="Final rating"><Select value={r.final_rating ?? ''} onChange={(v) => setR({ ...r, final_rating: v })} options={RATINGS} placeholder="—" /></Field>}
          </>
        )}
      </Modal>
    </Card>
  );
}

function Increments({ cycle }) {
  const { can } = useApp();
  const { data, reload } = useData(`/performance/cycles/${cycle.id}/increments`);
  const [pct, setPct] = useState({});
  const [run, busy] = useAction();
  const approveHr = async () => {
    const items = (data || []).filter((x) => x.status === 'proposed').map((x) => ({ employee_id: x.id, pct: pct[x.id] ?? x.pct, effective_from: x.effective_from }));
    if (await run(() => api.post(`/performance/cycles/${cycle.id}/increments`, items), `${items.length} increments sent to the GM`)) reload();
  };
  const gm = async (x, approve) => { if (await run(() => api.post(`/performance/increments/${x.increment_id}/gm?approve=${approve}`), approve ? 'Applied as a new salary version' : 'Sent back')) reload(); };
  return (
    <Card title="Merit matrix proposals" actions={<Button variant="primary" busy={busy} onClick={approveHr}>HR approve all proposed</Button>} pad={false}>
      <Table rows={data} cols={[{ label: 'Employee', render: (x) => `${x.code} ${x.name}` }, { key: 'grade', label: 'Grade' }, { key: 'rating', label: 'Rating', align: 'right' },
        { key: 'band_position', label: 'Pay band' }, { label: 'Current gross', align: 'right', render: (x) => money(x.current_gross) }, { label: 'Suggested', align: 'right', render: (x) => `${x.suggested_pct}%` },
        { label: 'Increment %', render: (x) => <input className="input input-s num" style={{ width: 80 }} disabled={x.status !== 'proposed'} value={pct[x.id] ?? x.pct} onChange={(e) => setPct({ ...pct, [x.id]: e.target.value })} /> },
        { label: 'From', render: (x) => fmtDate(x.effective_from) }, { label: 'Status', render: (x) => <Badge value={x.status}>{label(x.status)}</Badge> },
        { label: '', render: (x) => x.status === 'hr_approved' && can('increments.gm') && <span className="row gap-s"><Button size="s" variant="primary" busy={busy} onClick={() => gm(x, true)}>GM approve</Button><Button size="s" busy={busy} onClick={() => gm(x, false)}>Send back</Button></span> }]}
        empty="Increments appear once reviews have a final rating" />
    </Card>
  );
}
