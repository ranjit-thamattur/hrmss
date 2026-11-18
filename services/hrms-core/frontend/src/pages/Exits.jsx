import { useState } from 'react';
import { api, fmtDate, label, money, navigate, useAction, useData } from '../lib.jsx';
import { Badge, Button, Callout, Card, ErrorBox, Field, Loading, PageHeader, Table } from '../ui.jsx';

export function Exits() {
  const [status, setStatus] = useState('');
  const { data } = useData(`/exits${status ? `?status=${status}` : ''}`);
  return (
    <div className="stack">
      <PageHeader title="Exits & full and final" sub="Resignation → clearance → F&F (due in 2 working days) → letters → access removed. Record a resignation from the employee's page." />
      <Card pad={false}>
        <div className="filters">{[['', 'All'], ['notice', 'Notice period'], ['fnf_calculated', 'F&F calculated'], ['fnf_approved', 'F&F approved'], ['closed', 'Closed']].map(([k, l]) =>
          <button key={k} className={`chip ${status === k ? 'on' : ''}`} onClick={() => setStatus(k)}>{l}</button>)}</div>
        <Table rows={data} onRow={(x) => navigate(`/exits/${x.id}`)} cols={[{ label: 'Employee', render: (x) => <div><b>{x.employee.name}</b><div className="muted small">{x.employee.code} · {x.employee.location}</div></div> },
          { label: 'Resigned', render: (x) => fmtDate(x.resigned_on) }, { label: 'Last day', render: (x) => fmtDate(x.last_working_day) },
          { label: 'Clearance', render: (x) => `${x.clearance_done} / ${x.clearance_total}` }, { label: 'F&F due', render: (x) => fmtDate(x.fnf_due_on) }, { label: 'Status', render: (x) => <Badge value={x.status} /> }]} empty="No exits" />
      </Card>
    </div>
  );
}

export function ExitDetail({ id }) {
  const { data: x, error, loading, reload } = useData(`/exits/${id}`);
  const [run, busy] = useAction();
  const [f, setF] = useState({ el_balance_days: '', loan_balance: 0, advance_balance: 0, notice_waived: false });
  if (loading && !x) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const post = async (path, body, msg) => { if (await run(() => api.post(`/exits/${x.id}${path}`, body), msg)) reload(); };
  const pending = x.clearance.filter((t) => t.status !== 'done').length;
  return (
    <div className="stack">
      <PageHeader title={`Exit · ${x.employee.name}`} sub={`${x.employee.code} · resigned ${fmtDate(x.resigned_on)} · last day ${fmtDate(x.last_working_day)}`} actions={<>
        <Badge value={x.status} />
        {x.status === 'fnf_calculated' && <Button variant="primary" busy={busy} disabled={pending > 0} onClick={() => post('/fnf/approve', undefined, 'F&F approved')}>Approve F&F</Button>}
        {['fnf_approved', 'closed'].includes(x.status) && <>
          <Button onClick={() => api.download(`/exits/${x.id}/letter/relieving.pdf`)}>Relieving letter</Button>
          <Button onClick={() => api.download(`/exits/${x.id}/letter/experience.pdf`)}>Experience letter</Button></>}
        {x.status === 'fnf_approved' && <Button variant="danger" busy={busy} onClick={() => post('/close', undefined, 'Exit closed; access removal queued')}>Close exit and remove access</Button>}</>} />
      {x.reason && <Callout>Reason: {x.reason}</Callout>}
      <div className="grid g2">
        <Card title={`Clearance (${x.clearance.length - pending}/${x.clearance.length})`} pad={false}>
          <Table rows={x.clearance} cols={[{ key: 'department', label: 'Department' }, { key: 'item', label: 'Item' }, { key: 'owner', label: 'Owner' },
            { label: 'Status', render: (t) => <Badge value={t.status} /> },
            { label: '', render: (t) => x.status !== 'closed' && <Button size="s" busy={busy} onClick={() => post(`/clearance/${t.id}?done=${t.status !== 'done'}`, undefined, 'Saved')}>{t.status === 'done' ? 'Undo' : 'Mark done'}</Button> }]} />
        </Card>
        <Card title="Full and final settlement">
          {x.fnf ? (
            <div className="stack">
              <dl className="kv">
                {Object.entries(x.fnf.earnings).map(([k, v]) => [<dt key={`${k}l`}>{label(k.toLowerCase())}</dt>, <dd key={k}>{money(v)}</dd>])}
                {Object.entries(x.fnf.deductions).map(([k, v]) => [<dt key={`${k}l`}>Less {label(k.toLowerCase())}</dt>, <dd key={k}>{money(v)}</dd>])}
              </dl>
              <p><b>Net {money(x.fnf.net)}</b> · service {x.fnf.service} · gratuity {x.fnf.gratuity_eligible ? 'payable' : 'not yet eligible (under 5 years)'} · due {fmtDate(x.fnf.due_on)}</p>
            </div>
          ) : <p className="muted">Not calculated yet.</p>}
          {!['fnf_approved', 'closed'].includes(x.status) && (
            <div className="stack mt">
              <div className="grid g3">
                <Field label="EL balance (days)" hint="Empty = from leave balance"><input className="input" type="number" value={f.el_balance_days} onChange={(e) => setF({ ...f, el_balance_days: e.target.value })} /></Field>
                <Field label="Loan balance (₹)"><input className="input" type="number" value={f.loan_balance} onChange={(e) => setF({ ...f, loan_balance: e.target.value })} /></Field>
                <Field label="Advance balance (₹)"><input className="input" type="number" value={f.advance_balance} onChange={(e) => setF({ ...f, advance_balance: e.target.value })} /></Field>
              </div>
              <label className="check"><input type="checkbox" checked={f.notice_waived} onChange={(e) => setF({ ...f, notice_waived: e.target.checked })} /> Notice shortfall waived</label>
              <div><Button variant="primary" busy={busy} onClick={() => post('/fnf', { ...f, el_balance_days: f.el_balance_days === '' ? null : f.el_balance_days }, 'F&F calculated')}>{x.fnf ? 'Recalculate' : 'Calculate'} F&F</Button></div>
              {pending > 0 && <p className="muted small">{pending} clearance items must be done before the F&F can be approved.</p>}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
