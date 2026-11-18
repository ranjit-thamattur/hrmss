import { Fragment, useState } from 'react';
import { api, fmtDateTime, label, Link, money, navigate, qs, thisPeriod, useAction, useApp, useData } from '../lib.jsx';
import { Badge, Button, Callout, Card, ErrorBox, Field, Loading, Modal, PageHeader, Select, Stat, Table, Tabs } from '../ui.jsx';

const INPUT_CODES = ['SERVICE_CHARGE', 'INCENTIVE', 'ARREAR', 'BONUS', 'OTHER_EARNING', 'ADVANCE', 'LOAN_EMI', 'OTHER_DEDUCTION', 'TDS_OVERRIDE'];
const FLOW = ['calculated', 'reviewed', 'hr_approved', 'finance_approved', 'locked'];
const FLOW_LABEL = { calculated: 'Calculated', reviewed: 'Reviewed', hr_approved: 'HR approved', finance_approved: 'Finance approved', locked: 'Locked' };

export function PayrollHome() {
  const [tab, setTab] = useState('runs');
  return (
    <div className="stack">
      <PageHeader title="Payroll" sub="Calculated by fixed rules, never AI. Preparer reviews, HR approves, Finance approves, then it locks." />
      <Tabs tabs={[{ id: 'runs', label: 'Payroll runs' }, { id: 'inputs', label: 'Monthly inputs' }]} value={tab} onChange={setTab} />
      {tab === 'runs' ? <Runs /> : <Inputs />}
    </div>
  );
}

function Runs() {
  const { setup, can } = useApp();
  const { data, error } = useData('/payroll/runs');
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ entity_id: String(setup.entities[0]?.id || ''), period: thisPeriod(-1) });
  const [run, busy] = useAction();
  return (
    <>
      <Card title="Runs" actions={can('payroll.prepare') && <Button variant="primary" onClick={() => setOpen(true)}>New payroll run</Button>} pad={false}>
        <ErrorBox error={error} />
        <Table rows={data} onRow={(r) => navigate(`/payroll/runs/${r.id}`)} cols={[{ key: 'period', label: 'Period' }, { label: 'Entity', render: (r) => r.entity.code },
          { key: 'run_no', label: 'Run', align: 'right' }, { label: 'Status', render: (r) => <Badge value={r.status} /> }, { label: 'Staff', align: 'right', render: (r) => Number(r.totals?.headcount || 0) },
          { label: 'Net payable', align: 'right', render: (r) => money(r.totals?.net_payable) }, { label: 'Held', align: 'right', render: (r) => Number(r.totals?.held || 0) || '' },
          { key: 'prepared_by', label: 'Prepared by' }]} empty="No payroll runs yet" />
      </Card>
      <Modal open={open} title="New payroll run" onClose={() => setOpen(false)} footer={<Button variant="primary" busy={busy} onClick={async () => {
        const r = await run(() => api.post('/payroll/runs', { entity_id: Number(f.entity_id), period: f.period }), 'Payroll calculated');
        if (r) navigate(`/payroll/runs/${r.id}`);
      }}>Calculate</Button>}>
        <Field label="Paying entity"><Select value={f.entity_id} onChange={(v) => setF({ ...f, entity_id: v })} options={setup.entities.map((e) => ({ value: e.id, label: `${e.code} · ${e.name}` }))} /></Field>
        <Field label="Period"><input className="input" type="month" value={f.period} onChange={(e) => setF({ ...f, period: e.target.value })} /></Field>
        <p className="muted small">Attendance for the period is locked when the run is calculated. Split-salary staff appear in each paying entity's run for their share.</p>
      </Modal>
    </>
  );
}

function Inputs() {
  const { setup, can } = useApp();
  const [period, setPeriod] = useState(thisPeriod(-1));
  const [entity, setEntity] = useState('');
  const [q, setQ] = useState('');
  const { data, reload } = useData(`/payroll/inputs${qs({ period, entity_id: entity })}`);
  const [edits, setEdits] = useState({});
  const [run, busy] = useAction();
  const rows = (data?.items || []).filter((r) => !q || `${r.code} ${r.name}`.toLowerCase().includes(q.toLowerCase()));
  const save = async () => {
    const out = Object.entries(edits).map(([k, amount]) => { const [employee_id, code] = k.split('|'); return { employee_id: Number(employee_id), code, amount: amount || 0 }; });
    if (await run(() => api.put('/payroll/inputs', { period, rows: out }), `${out.length} values saved`)) { setEdits({}); reload(); }
  };
  const editable = can('payroll.prepare') && !data?.locked;
  return (
    <Card pad={false}>
      <div className="filters">
        <input className="input input-s" type="month" value={period} onChange={(e) => { setPeriod(e.target.value); setEdits({}); }} />
        <Select className="input input-s" value={entity} onChange={setEntity} options={setup.entities.map((e) => ({ value: e.id, label: e.code }))} placeholder="All entities" />
        <input className="input input-s" placeholder="Find employee" value={q} onChange={(e) => setQ(e.target.value)} />
        <Button size="s" onClick={() => navigate('/imports')}>Import from Excel</Button>
        {editable && <Button size="s" variant="primary" disabled={!Object.keys(edits).length} busy={busy} onClick={save}>Save {Object.keys(edits).length || ''} changes</Button>}
        {data?.locked && <Badge tone="green">Locked by payroll</Badge>}
      </div>
      <div className="tbl-wrap">
        <table className="tbl">
          <thead><tr><th>Employee</th>{INPUT_CODES.map((c) => <th key={c} style={{ textAlign: 'right' }}>{label(c.toLowerCase())}</th>)}</tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td><b>{r.name}</b><div className="muted small">{r.code} · {r.entity}</div></td>
                {INPUT_CODES.map((c) => {
                  const k = `${r.id}|${c}`;
                  return <td key={c} className="roster-cell"><input className={`cell-in num ${k in edits ? 'changed' : ''}`} inputMode="decimal" disabled={!editable}
                    value={k in edits ? edits[k] : (r.inputs[c] ?? '')} onChange={(e) => setEdits({ ...edits, [k]: e.target.value })} /></td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export function PayrollRun({ id }) {
  const { me, can } = useApp();
  const { data: r, error, loading, reload } = useData(`/payroll/runs/${id}`);
  const [run, busy] = useAction();
  const [view, setView] = useState('flagged');
  const [line, setLine] = useState(null);
  const [note, setNote] = useState('');
  const [back, setBack] = useState(false);
  if (loading && !r) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const t = r.totals || {};
  const step = async (path, msg) => { const x = await run(() => api.post(`/payroll/runs/${r.id}/${path}`), msg); if (x) reload(); };
  const editable = ['calculated', 'reviewed'].includes(r.status) && can('payroll.prepare');
  const lines = r.lines.filter((l) => (view === 'flagged' ? l.flags.length : view === 'held' ? l.hold : true));
  const decide = async (decision) => {
    const x = await run(() => api.post(`/payroll/lines/${line.id}/decide`, { decision, note }), `Line ${decision === 'release' ? 'reopened' : decision === 'hold' ? 'held' : 'accepted'}`);
    if (x) { setLine(null); setNote(''); reload(); }
  };
  const mine = (who) => who && who === me.email;
  return (
    <div className="stack">
      <PageHeader title={`Payroll ${r.period} · ${r.entity.code}`} sub={`${r.entity.name} · run ${r.run_no} · rules ${r.rule_version || '—'} · missed-punch rule: ${label(r.missed_punch_rule || 'not set')}`} actions={<>
        <Badge value={r.status} />
        {editable && <Button busy={busy} onClick={() => step('recalculate', 'Recalculated')}>Recalculate</Button>}
        {r.status === 'calculated' && can('payroll.prepare') && <Button variant="primary" busy={busy} onClick={() => step('submit', 'Sent to HR for approval')}>Submit for approval</Button>}
        {r.status === 'reviewed' && can('payroll.approve_hr') && <Button variant="primary" busy={busy} disabled={mine(r.prepared_by)} onClick={() => step('approve-hr', 'HR approved')}>HR approve</Button>}
        {r.status === 'hr_approved' && can('payroll.approve_finance') && <Button variant="primary" busy={busy} disabled={mine(r.prepared_by) || mine(r.hr_approved_by)} onClick={() => step('approve-finance', 'Finance approved')}>Finance approve</Button>}
        {r.status === 'finance_approved' && can('payroll.approve_finance') && <Button variant="primary" busy={busy} onClick={() => step('lock', 'Payroll locked')}>Lock payroll</Button>}
        {['reviewed', 'hr_approved', 'finance_approved'].includes(r.status) && (can('payroll.approve_hr') || can('payroll.approve_finance')) && <Button variant="danger" onClick={() => setBack(true)}>Send back</Button>}
      </>} />
      <div className="steps">{FLOW.map((s, i) => <div key={s} className={`step ${FLOW.indexOf(r.status) >= i ? 'done' : ''} ${r.status === s ? 'now' : ''}`}><span>{i + 1}</span>{FLOW_LABEL[s]}</div>)}</div>
      {(mine(r.prepared_by) && ['reviewed', 'hr_approved'].includes(r.status)) && <Callout>You prepared this payroll, so another person must approve it.</Callout>}
      {Number(t.undecided) > 0 && <Callout tone="amber">{Number(t.undecided)} flagged lines need a decision (accept with a note, or hold) before the run can be submitted. Negative pay can only be held or fixed.</Callout>}
      <div className="grid g4">
        <Stat label="Staff" value={Number(t.headcount || 0)} />
        <Stat label="Gross" value={money(t.gross)} />
        <Stat label="Net payable (bank file)" value={money(t.net_payable)} />
        <Stat label="Held / flagged" value={`${Number(t.held || 0)} / ${Number(t.flagged || 0)}`} tone={Number(t.held) ? 'amber' : undefined} />
      </div>
      <div className="grid g2">
        <Card title="Statutory totals">
          <dl className="kv">{['PF', 'EPF_ER', 'EPS', 'EDLI', 'PF_ADMIN', 'ESI', 'ESI_ER', 'PT', 'LWF', 'LWF_ER', 'TDS'].filter((k) => t[k] && Number(t[k])).map((k) => <Fragment key={k}><dt>{k}</dt><dd>{money(t[k])}</dd></Fragment>)}</dl>
        </Card>
        <Card title="Files">
          {r.status !== 'locked' ? <p className="muted">Bank, Tally, EPF ECR and ESI files are created only after the run is locked.</p> : (
            <div className="row gap-s wrap">
              {[['register.csv', 'Register'], ['bank.csv', 'Bank file'], ['tally.xml', 'Tally journal'], ['epf-ecr.txt', 'EPF ECR'], ['esi.csv', 'ESI']].map(([f, l]) =>
                <Button key={f} size="s" onClick={() => api.download(`/payroll/runs/${r.id}/${f}`)}>{l}</Button>)}
              {can('payroll.prepare') && <Button size="s" variant="primary" busy={busy} disabled={r.payslips_published} onClick={() => step('publish', 'Payslips queued to staff')}>{r.payslips_published ? 'Payslips published' : 'Publish payslips'}</Button>}
            </div>
          )}
          <ol className="small muted mt">{(r.steps || []).map((s, i) => <li key={i}><b>{s.step}</b> · {s.detail} · {fmtDateTime(s.at)}</li>)}</ol>
        </Card>
      </div>
      <Card pad={false}>
        <div className="filters">{[['flagged', `Flagged (${r.lines.filter((l) => l.flags.length).length})`], ['held', `Held (${r.lines.filter((l) => l.hold).length})`], ['all', `All (${r.lines.length})`]].map(([k, l]) =>
          <button key={k} className={`chip ${view === k ? 'on' : ''}`} onClick={() => setView(k)}>{l}</button>)}</div>
        <Table rows={lines} onRow={(l) => { setLine(l); setNote(l.decision_note || ''); }} rowClass={(l) => (l.hold ? 'row-held' : '')} cols={[
          { label: 'Employee', render: (l) => <div><b>{l.name}</b><div className="muted small">{l.code}{l.split ? ` · split ${Number(l.share_pct)}%` : ''}</div></div> },
          { key: 'paid_days', label: 'Paid days', align: 'right' }, { key: 'lop_days', label: 'LOP', align: 'right' }, { key: 'ot_hours', label: 'OT h', align: 'right' },
          { label: 'Gross', align: 'right', render: (l) => money(l.gross) }, { label: 'Deductions', align: 'right', render: (l) => money(l.total_deductions) },
          { label: 'Net', align: 'right', render: (l) => <b className={Number(l.net) < 0 ? 'red' : ''}>{money(l.net)}</b> },
          { label: 'Checks', render: (l) => <span className="row gap-s wrap">{l.flags.map((f) => <Badge key={f.code} value={f.severity}>{label(f.code.toLowerCase())}</Badge>)}</span> },
          { label: 'Decision', render: (l) => (l.decision ? <Badge value={l.decision} /> : l.flags.length ? <Badge tone="amber">Needed</Badge> : '') },
        ]} />
      </Card>
      <Modal open={!!line} wide title={line ? `${line.name} · ${line.code}` : ''} onClose={() => setLine(null)} footer={line && <>
        {r.status === 'locked' && <Button onClick={() => api.download(`/payroll/runs/${r.id}/payslips/${line.employee_id}.pdf`)}>Payslip PDF</Button>}
        {editable && <>
          {line.decision && <Button variant="ghost" busy={busy} onClick={() => decide('release')}>Clear decision</Button>}
          <Button variant="danger" busy={busy} onClick={() => decide('hold')}>Hold pay</Button>
          <Button variant="primary" busy={busy} disabled={line.flags.some((f) => f.code === 'NEGATIVE_NET')} onClick={() => decide('accept')}>Accept</Button>
        </>}</>}>
        {line && (
          <div className="stack">
            {line.flags.map((f) => <Callout key={f.code} tone={f.severity === 'block' ? 'red' : 'amber'}><b>{label(f.code.toLowerCase())}:</b> {f.message}</Callout>)}
            <div className="grid g3">
              <Breakdown title="Earnings" items={line.earnings} total={line.gross} />
              <Breakdown title="Deductions" items={line.deductions} total={line.total_deductions} />
              <Breakdown title="Employer cost" items={line.employer} />
            </div>
            <p><b>Net pay {money(line.net)}</b> · paid days {line.paid_days} · LOP {line.lop_days}</p>
            {editable && <Field label="Note (required to accept or hold a blocking check)"><textarea className="input" rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></Field>}
            {line.decided_by && <p className="muted small">Decision by {line.decided_by}: {line.decision_note}</p>}
            {editable && <p className="muted small">To fix a figure, change the monthly inputs or attendance, then Recalculate. <Link to="/payroll">Monthly inputs</Link></p>}
          </div>
        )}
      </Modal>
      <Modal open={back} title="Send back to the preparer" onClose={() => setBack(false)} footer={<Button variant="danger" busy={busy} onClick={async () => {
        if (await run(() => api.post(`/payroll/runs/${r.id}/send-back?note=${encodeURIComponent(note)}`), 'Sent back')) { setBack(false); setNote(''); reload(); }
      }}>Send back</Button>}>
        <Field label="What needs to change"><textarea className="input" rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </Modal>
    </div>
  );
}

function Breakdown({ title, items, total }) {
  const rows = Object.entries(items || {}).filter(([, v]) => Number(v));
  return (
    <div>
      <h4>{title}</h4>
      <dl className="kv">{rows.map(([k, v]) => <Fragment key={k}><dt>{k.replace(/_/g, ' ')}</dt><dd>{money(v)}</dd></Fragment>)}</dl>
      {total !== undefined && <p className="mt"><b>{money(total)}</b></p>}
    </div>
  );
}
