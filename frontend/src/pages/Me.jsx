import { useState } from 'react';
import { api, fmtDate, fmtTime, label, money, today, useAction, useApp, useData, useRoute } from '../lib.jsx';
import { Badge, Button, Callout, Card, ErrorBox, Field, Loading, Modal, PageHeader, Select, Table, Tabs } from '../ui.jsx';

export default function Me() {
  const { search } = useRoute();
  const [tab, setTab] = useState(search.get('tab') || 'profile');
  const { data: p, error, loading, reload } = useData('/me/profile');
  if (loading && !p) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  return (
    <div className="stack">
      <PageHeader title="My HR" sub={`${p.name} · ${p.code} · ${p.designation || ''} · ${p.location}`} />
      <Tabs tabs={[{ id: 'profile', label: 'My details' }, { id: 'payslips', label: 'Payslips' }, { id: 'attendance', label: 'Attendance' }, { id: 'leave', label: 'Leave' }, { id: 'exit', label: 'Resignation' }]} value={tab} onChange={setTab} />
      {tab === 'profile' && <Profile p={p} reload={reload} />}
      {tab === 'payslips' && <Payslips />}
      {tab === 'attendance' && <MyAttendance />}
      {tab === 'leave' && <MyLeave />}
      {tab === 'exit' && <MyExit />}
    </div>
  );
}

const FIELDS = [['phone', 'Mobile'], ['email', 'Email'], ['address', 'Address'], ['language', 'Language'], ['bank_account', 'Bank account'], ['ifsc', 'IFSC'], ['bank_name', 'Bank name'], ['pan', 'PAN']];

function Profile({ p, reload }) {
  const [f, setF] = useState(null);
  const [run, busy] = useAction();
  return (
    <div className="grid g2">
      <Card title="My details" actions={<Button size="s" onClick={() => setF({ field: 'phone', new_value: '', reason: '' })}>Request a change</Button>}>
        <dl className="kv">
          <dt>Mobile</dt><dd>{p.phone || '—'}</dd><dt>Email</dt><dd>{p.email || '—'}</dd><dt>Joined</dt><dd>{fmtDate(p.doj)}</dd><dt>Department</dt><dd>{p.department}</dd>
          <dt>Manager</dt><dd>{p.manager || '—'}</dd><dt>PAN</dt><dd className="mono">{p.pan || '—'}</dd><dt>Bank</dt><dd className="mono">{p.bank_account || '—'} {p.ifsc}</dd><dt>UAN</dt><dd className="mono">{p.uan || '—'}</dd>
        </dl>
        <p className="muted small mt">Changes to bank or PAN are checked by HR before they apply.</p>
      </Card>
      <Card title="My change requests" pad={false}>
        <Table rows={p.change_requests} cols={[{ label: 'Field', render: (c) => label(c.field) }, { label: 'Status', render: (c) => <Badge value={c.status} /> }, { label: 'Raised', render: (c) => fmtDate(c.created_at) }]} empty="None" />
      </Card>
      <Modal open={!!f} title="Request a change" onClose={() => setF(null)} footer={<Button variant="primary" busy={busy} onClick={async () => { if (await run(() => api.post('/me/change-requests', f), 'Sent to HR')) { setF(null); reload(); } }}>Send to HR</Button>}>
        {f && <>
          <Field label="What to change"><Select value={f.field} onChange={(v) => setF({ ...f, field: v })} options={FIELDS.map(([value, l]) => ({ value, label: l }))} /></Field>
          <Field label="New value"><input className="input" value={f.new_value} onChange={(e) => setF({ ...f, new_value: e.target.value })} /></Field>
          <Field label="Reason"><input className="input" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} /></Field>
        </>}
      </Modal>
    </div>
  );
}

function Payslips() {
  const { me } = useApp();
  const { data } = useData('/me/payslips');
  return (
    <Card pad={false}>
      <Table rows={data} rowKey={(s) => s.run_id} cols={[{ key: 'period', label: 'Month' }, { key: 'paid_days', label: 'Paid days', align: 'right' }, { label: 'Gross', align: 'right', render: (s) => money(s.gross) },
        { label: 'Net pay', align: 'right', render: (s) => <b>{money(s.net)}</b> }, { label: '', render: (s) => <Button size="s" onClick={() => api.download(`/payroll/runs/${s.run_id}/payslips/${me.employee_id}.pdf`)}>Download PDF</Button> }]} empty="No payslips yet" />
    </Card>
  );
}

function MyAttendance() {
  const [ym, setYm] = useState(today().slice(0, 7));
  const [y, m] = ym.split('-').map(Number);
  const { data } = useData(`/me/attendance?year=${y}&month=${m}`);
  const [reg, setReg] = useState(null);
  const [run, busy] = useAction();
  return (
    <Card title="My attendance" actions={<input className="input input-s" type="month" value={ym} onChange={(e) => setYm(e.target.value)} />} pad={false}>
      <Table rows={data} cols={[{ label: 'Date', render: (d) => fmtDate(d.work_date) }, { key: 'shift_code', label: 'Shift' }, { label: 'Status', render: (d) => <Badge value={d.status} /> },
        { label: 'In', render: (d) => fmtTime(d.first_in) }, { label: 'Out', render: (d) => fmtTime(d.last_out) }, { label: 'OT', render: (d) => (d.ot_minutes ? `${(d.ot_minutes / 60).toFixed(1)} h` : '') },
        { label: '', render: (d) => d.status === 'missed_punch' && !d.locked && <Button size="s" onClick={() => setReg({ work_date: d.work_date, in_time: '', out_time: '', reason: '' })}>Ask to fix</Button> }]} empty="No attendance for this month" />
      <Modal open={!!reg} title={`Fix punch · ${fmtDate(reg?.work_date)}`} onClose={() => setReg(null)} footer={<Button variant="primary" busy={busy} onClick={async () => { if (await run(() => api.post('/regularisations', reg), 'Sent to your HOD')) setReg(null); }}>Send</Button>}>
        {reg && <>
          <div className="grid g2">
            <Field label="In"><input className="input" type="time" value={reg.in_time} onChange={(e) => setReg({ ...reg, in_time: e.target.value })} /></Field>
            <Field label="Out"><input className="input" type="time" value={reg.out_time} onChange={(e) => setReg({ ...reg, out_time: e.target.value })} /></Field>
          </div>
          <Field label="Reason"><input className="input" value={reg.reason} onChange={(e) => setReg({ ...reg, reason: e.target.value })} /></Field>
        </>}
      </Modal>
    </Card>
  );
}

function MyLeave() {
  const { data: bal, reload: rb } = useData('/leave/balances');
  const { data: reqs, reload } = useData('/leave/requests?mine=true');
  const [f, setF] = useState(null);
  const [run, busy] = useAction();
  return (
    <div className="stack">
      <div className="grid g4">{(bal || []).map((b) => <div key={b.leave_code} className="stat"><div className="stat-l">{b.name}</div><div className="stat-v">{Number(b.available)}</div><div className="stat-s">of {Number(b.opening)} · used {Number(b.used)}</div></div>)}</div>
      <Card title="My leave" actions={<Button variant="primary" onClick={() => setF({ leave_code: 'CL', from_date: today(), to_date: today(), half_day: false, reason: '' })}>Apply for leave</Button>} pad={false}>
        <Table rows={reqs} cols={[{ key: 'leave_code', label: 'Type' }, { label: 'From', render: (r) => fmtDate(r.from_date) }, { label: 'To', render: (r) => fmtDate(r.to_date) }, { key: 'days', label: 'Days', align: 'right' },
          { label: 'Status', render: (r) => <Badge value={r.status}>{label(r.status)}</Badge> },
          { label: '', render: (r) => r.status.startsWith('pending') && <Button size="s" variant="ghost" busy={busy} onClick={async () => { if (await run(() => api.post(`/leave/requests/${r.id}/cancel`), 'Cancelled')) reload(); }}>Cancel</Button> }]} empty="No leave yet" />
      </Card>
      <Modal open={!!f} title="Apply for leave" onClose={() => setF(null)} footer={<Button variant="primary" busy={busy} onClick={async () => { if (await run(() => api.post('/leave/requests', f), 'Sent to your HOD')) { setF(null); reload(); rb(); } }}>Apply</Button>}>
        {f && <>
          <Field label="Type"><Select value={f.leave_code} onChange={(v) => setF({ ...f, leave_code: v })} options={(bal || []).map((b) => ({ value: b.leave_code, label: `${b.name} (${Number(b.available)} left)` }))} /></Field>
          <div className="grid g2">
            <Field label="From"><input className="input" type="date" value={f.from_date} onChange={(e) => setF({ ...f, from_date: e.target.value })} /></Field>
            <Field label="To"><input className="input" type="date" value={f.to_date} onChange={(e) => setF({ ...f, to_date: e.target.value })} /></Field>
          </div>
          <label className="check"><input type="checkbox" checked={f.half_day} onChange={(e) => setF({ ...f, half_day: e.target.checked })} /> Half day</label>
          <Field label="Reason"><input className="input" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} /></Field>
        </>}
      </Modal>
    </div>
  );
}

function MyExit() {
  const { data, reload } = useData('/me/exit');
  const [f, setF] = useState({ reason: '' });
  const [run, busy] = useAction();
  if (data) {
    return (
      <Card title="My resignation">
        <dl className="kv"><dt>Resigned on</dt><dd>{fmtDate(data.resigned_on)}</dd><dt>Last working day</dt><dd>{fmtDate(data.last_working_day)}</dd><dt>Status</dt><dd><Badge value={data.status} /></dd>
          <dt>F&F due</dt><dd>{fmtDate(data.fnf_due_on)}</dd></dl>
      </Card>
    );
  }
  return (
    <Card title="Resign">
      <Callout>Your last working day is set from your notice period. HR will contact you about clearance and your full and final settlement.</Callout>
      <Field label="Reason (optional)"><textarea className="input" rows={3} value={f.reason} onChange={(e) => setF({ reason: e.target.value })} /></Field>
      <Button variant="danger" busy={busy} onClick={async () => { if (await run(() => api.post('/exits', f), 'Resignation submitted')) reload(); }}>Submit resignation</Button>
    </Card>
  );
}
