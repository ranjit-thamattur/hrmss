import { useState } from 'react';
import { api, fmtDate, fmtTime, label, Link, qs, today, useAction, useApp, useData } from '../lib.jsx';
import { Badge, Button, Callout, Card, Field, Modal, PageHeader, Select, Table, Tabs } from '../ui.jsx';

const monthStart = () => `${today().slice(0, 8)}01`;

export default function Attendance() {
  const { can } = useApp();
  const [tab, setTab] = useState('exceptions');
  const [run, busy] = useAction();
  const [ym, setYm] = useState(today().slice(0, 7));
  const [y, mo] = ym.split('-').map(Number);
  const [stamp, setStamp] = useState(0);
  return (
    <div className="stack">
      <PageHeader title="Attendance" sub="Punches from the biometric device (or its Excel export) become days. Fix exceptions before payroll." actions={can('attendance.manage') && <>
        <input className="input input-s" type="month" value={ym} onChange={(e) => setYm(e.target.value)} />
        <Button busy={busy} onClick={async () => { if (await run(() => api.post('/attendance/sync'), 'Device sync done')) setStamp(stamp + 1); }}>Sync device</Button>
        <Button variant="primary" busy={busy} onClick={async () => { const r = await run(() => api.post('/attendance/process', { year: y, month: mo }), 'Attendance processed'); if (r) setStamp(stamp + 1); }}>Process month</Button></>} />
      <Tabs tabs={[{ id: 'exceptions', label: 'Exceptions' }, { id: 'days', label: 'Daily register' }, { id: 'summary', label: 'Month summary' }, { id: 'roster', label: 'Shift roster' }]} value={tab} onChange={setTab} />
      {tab === 'exceptions' && <Exceptions key={`e${stamp}${ym}`} ym={ym} />}
      {tab === 'days' && <Days key={`d${stamp}`} />}
      {tab === 'summary' && <Summary key={`s${stamp}${ym}`} y={y} mo={mo} />}
      {tab === 'roster' && <Roster />}
    </div>
  );
}

const lastDay = (ym) => { const [y, m] = ym.split('-').map(Number); const d = new Date(Date.UTC(y, m, 0)); return d.toISOString().slice(0, 10); };

function Exceptions({ ym }) {
  const { can } = useApp();
  const to = lastDay(ym) < today() ? lastDay(ym) : today();
  const { data, reload } = useData(`/attendance/exceptions${qs({ date_from: `${ym}-01`, date_to: to })}`);
  const [run, busy] = useAction();
  const [fix, setFix] = useState(null);
  const [part, setPart] = useState('missed_punch');
  if (!data) return null;
  const empCol = { label: 'Employee', render: (d) => <div><b>{d.employee.name}</b><div className="muted small">{d.employee.code} · {d.employee.department}</div></div> };
  const common = [empCol, { label: 'Date', render: (d) => fmtDate(d.work_date) }, { key: 'shift_code', label: 'Shift' }, { label: 'In', render: (d) => fmtTime(d.first_in) }, { label: 'Out', render: (d) => fmtTime(d.last_out) }];
  const ot = async (d, approve) => { if (await run(() => api.post(`/attendance/days/${d.id}/ot?approve=${approve}`), approve ? 'OT approved' : 'OT rejected')) reload(); };
  const cols = {
    missed_punch: [...common, { label: '', render: (d) => can('attendance.manage') && <span className="row gap-s"><Button size="s" onClick={() => setFix({ ...d, in_time: '', out_time: '' })}>Fix times</Button>
      <Button size="s" variant="ghost" busy={busy} onClick={async () => { if (await run(() => api.post(`/attendance/days/${d.id}/resolve`, { mark: 'present' }), 'Marked present')) reload(); }}>Mark present</Button>
      <Button size="s" variant="ghost" busy={busy} onClick={async () => { if (await run(() => api.post(`/attendance/days/${d.id}/resolve`, { mark: 'absent' }), 'Marked absent')) reload(); }}>Mark absent</Button></span> }],
    late: [...common, { key: 'late_minutes', label: 'Late (min)', align: 'right' }],
    ot_pending: [...common, { label: 'OT', align: 'right', render: (d) => `${(d.ot_minutes / 60).toFixed(1)} h` },
      { label: '', render: (d) => <span className="row gap-s"><Button size="s" variant="primary" busy={busy} onClick={() => ot(d, true)}>Approve</Button><Button size="s" variant="danger" busy={busy} onClick={() => ot(d, false)}>Reject</Button></span> }],
    absent: common,
  };
  return (
    <>
      {!data.missed_punch_rule && <Callout tone="amber">Missed-punch rule not set: payroll stays blocked while any missed punch is open. Fix each one, or set the rule in <Link to="/settings">Company setup</Link>.</Callout>}
      {data.missed_punch_rule && <Callout>Open missed punches will be treated as <b>{label(data.missed_punch_rule)}</b> in payroll.</Callout>}
      <Card pad={false}>
        <div className="filters">
          {[['missed_punch', 'Missed punch'], ['ot_pending', 'OT to approve'], ['late', 'Late'], ['absent', 'Absent']].map(([k, l]) => <button key={k} className={`chip ${part === k ? 'on' : ''}`} onClick={() => setPart(k)}>{l} ({data[k].length})</button>)}
          <span className="muted small">{fmtDate(data.from)} – {fmtDate(data.to)}</span>
        </div>
        <Table rows={data[part]} cols={cols[part]} empty="Nothing here" />
      </Card>
      <Modal open={!!fix} title={`Fix punches · ${fix?.employee.name} · ${fmtDate(fix?.work_date)}`} onClose={() => setFix(null)} footer={<Button variant="primary" busy={busy} onClick={async () => {
        if (await run(() => api.post(`/attendance/days/${fix.id}/resolve`, { in_time: fix.in_time, out_time: fix.out_time }), 'Day corrected')) { setFix(null); reload(); }
      }}>Save</Button>}>
        <p className="muted small">Out earlier than in means the shift ended the next morning.</p>
        <div className="grid g2">
          <Field label="In time"><input className="input" type="time" value={fix?.in_time || ''} onChange={(e) => setFix({ ...fix, in_time: e.target.value })} /></Field>
          <Field label="Out time"><input className="input" type="time" value={fix?.out_time || ''} onChange={(e) => setFix({ ...fix, out_time: e.target.value })} /></Field>
        </div>
      </Modal>
    </>
  );
}

function Days() {
  const { setup } = useApp();
  const [f, setF] = useState({ date_from: monthStart(), date_to: today(), location_id: '', status: '' });
  const { data } = useData(`/attendance/days${qs({ ...f, limit: 1000 })}`);
  return (
    <Card pad={false}>
      <div className="filters">
        <input className="input input-s" type="date" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} />
        <input className="input input-s" type="date" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} />
        <Select className="input input-s" value={f.location_id} onChange={(v) => setF({ ...f, location_id: v })} options={setup.locations.map((l) => ({ value: l.id, label: l.name }))} placeholder="All locations" />
        <Select className="input input-s" value={f.status} onChange={(v) => setF({ ...f, status: v })} options={['present', 'absent', 'missed_punch', 'leave', 'holiday', 'weekly_off', 'half_day']} placeholder="Any status" />
        <span className="muted small">{data?.length ?? 0} days (max 1,000 shown)</span>
      </div>
      <Table rows={data} cols={[{ label: 'Date', render: (d) => fmtDate(d.work_date) }, { label: 'Employee', render: (d) => `${d.employee.code} ${d.employee.name}` }, { key: 'shift_code', label: 'Shift' },
        { label: 'Status', render: (d) => <Badge value={d.status} /> }, { label: 'In', render: (d) => fmtTime(d.first_in) }, { label: 'Out', render: (d) => fmtTime(d.last_out) },
        { label: 'Worked', align: 'right', render: (d) => `${(d.worked_minutes / 60).toFixed(1)} h` }, { label: 'Late', align: 'right', render: (d) => (d.late_minutes ? `${d.late_minutes} m` : '') },
        { label: 'OT', align: 'right', render: (d) => (d.ot_minutes ? `${(d.ot_minutes / 60).toFixed(1)} h${d.ot_approved ? '' : ' (pending)'}` : '') },
        { label: '', render: (d) => <span className="row gap-s">{d.regularised && <Badge tone="blue">Fixed</Badge>}{d.locked && <Badge>Locked</Badge>}</span> }]} />
    </Card>
  );
}

function Summary({ y, mo }) {
  const { data } = useData(`/attendance/summary?year=${y}&month=${mo}`);
  if (!data) return null;
  return (
    <>
      {data.blocked > 0 && <Callout tone="amber">{data.blocked} employees have open missed punches and no rule is set, so their month cannot be summarised yet.</Callout>}
      <Card pad={false}>
        <Table rows={data.items} cols={[{ label: 'Employee', render: (r) => `${r.code} ${r.name}` }, { key: 'department', label: 'Department' },
          { key: 'present', label: 'Present', align: 'right' }, { key: 'absent', label: 'Absent', align: 'right' }, { key: 'leave_paid', label: 'Paid leave', align: 'right' },
          { key: 'weekly_off', label: 'Off', align: 'right' }, { key: 'holidays', label: 'Hol.', align: 'right' }, { key: 'lop_days', label: 'LOP', align: 'right' },
          { key: 'paid_days', label: 'Paid days', align: 'right' }, { key: 'ot_hours', label: 'OT h', align: 'right' }, { key: 'night_shifts', label: 'Nights', align: 'right' },
          { label: '', render: (r) => (r.error ? <span className="small red">{r.error}</span> : r.missed_open ? <Badge tone="amber">{r.missed_open} missed</Badge> : '') }]} />
      </Card>
    </>
  );
}

const monday = () => { const d = new Date(); const day = (d.getDay() + 6) % 7; d.setDate(d.getDate() - day); return d.toISOString().slice(0, 10); };

function Roster() {
  const { setup, can } = useApp();
  const [week, setWeek] = useState(monday());
  const [loc, setLoc] = useState(String(setup.locations[0]?.id || ''));
  const [dept, setDept] = useState('');
  const { data, reload } = useData(`/attendance/roster${qs({ week_start: week, location_id: loc, department_id: dept })}`);
  const [changes, setChanges] = useState({});
  const [run, busy] = useAction();
  const shiftOpts = (data?.shifts || []).map((s) => s.code);
  const save = async () => {
    const entries = Object.entries(changes).map(([k, shift_code]) => { const [employee_id, day] = k.split('|'); return { employee_id: Number(employee_id), day, shift_code }; });
    if (await run(() => api.put('/attendance/roster', { entries }), `${entries.length} shifts saved`)) { setChanges({}); reload(); }
  };
  return (
    <Card pad={false}>
      <div className="filters">
        <Field label="Week from"><input className="input input-s" type="date" value={week} onChange={(e) => setWeek(e.target.value)} /></Field>
        <Select className="input input-s" value={loc} onChange={setLoc} options={setup.locations.map((l) => ({ value: l.id, label: l.name }))} />
        <Select className="input input-s" value={dept} onChange={setDept} options={setup.departments.map((d) => ({ value: d.id, label: d.name }))} placeholder="All departments" />
        {can('attendance.manage') && <Button variant="primary" size="s" disabled={!Object.keys(changes).length} busy={busy} onClick={save}>Save {Object.keys(changes).length || ''} changes</Button>}
      </div>
      {data && (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead><tr><th>Employee</th>{data.days.map((d) => <th key={d}>{new Date(d).toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit' })}</th>)}</tr></thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.id}>
                  <td><b>{r.name}</b><div className="muted small">{r.code}</div></td>
                  {r.cells.map((c, i) => {
                    const k = `${r.id}|${data.days[i]}`;
                    return (
                      <td key={k} className="roster-cell">
                        <select className={`cell-in ${changes[k] ? 'changed' : ''}`} value={changes[k] ?? c} disabled={!can('attendance.manage')} onChange={(e) => setChanges({ ...changes, [k]: e.target.value })}>
                          {shiftOpts.map((s) => <option key={s}>{s}</option>)}
                        </select>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
