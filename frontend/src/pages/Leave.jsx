import { useState } from 'react';
import { api, fmtDate, label, useAction, useData } from '../lib.jsx';
import { Badge, Button, Card, PageHeader, Table } from '../ui.jsx';

export default function Leave() {
  const [status, setStatus] = useState('pending_hod');
  const { data, reload } = useData(`/leave/requests${status ? `?status=${status}` : ''}`);
  const [run, busy] = useAction();
  const decide = async (r, approve) => { if (await run(() => api.post(`/leave/requests/${r.id}/decide?approve=${approve}`), approve ? 'Leave approved' : 'Leave rejected')) reload(); };
  return (
    <div className="stack">
      <PageHeader title="Leave" sub="The HOD approves first. Long leave (over the policy limit) goes on to HR." />
      <Card pad={false}>
        <div className="filters">{[['pending_hod', 'Waiting for HOD'], ['pending_hr', 'Waiting for HR'], ['approved', 'Approved'], ['rejected', 'Rejected'], ['', 'All']].map(([k, l]) =>
          <button key={k} className={`chip ${status === k ? 'on' : ''}`} onClick={() => setStatus(k)}>{l}</button>)}</div>
        <Table rows={data} cols={[{ label: 'Employee', render: (r) => <div><b>{r.employee.name}</b><div className="muted small">{r.employee.code} · {r.employee.department}</div></div> },
          { key: 'leave_code', label: 'Type' }, { label: 'From', render: (r) => fmtDate(r.from_date) }, { label: 'To', render: (r) => fmtDate(r.to_date) },
          { key: 'days', label: 'Days', align: 'right' }, { key: 'reason', label: 'Reason' }, { label: 'Status', render: (r) => <Badge value={r.status}>{label(r.status)}</Badge> },
          { label: '', render: (r) => r.status.startsWith('pending') && <span className="row gap-s">
            <Button size="s" variant="primary" busy={busy} onClick={() => decide(r, true)}>Approve</Button>
            <Button size="s" variant="danger" busy={busy} onClick={() => decide(r, false)}>Reject</Button></span> }]} empty="No leave requests" />
      </Card>
    </div>
  );
}
