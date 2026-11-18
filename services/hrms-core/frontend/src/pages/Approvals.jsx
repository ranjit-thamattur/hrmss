import { useState } from 'react';
import { api, fmtDate, label, navigate, useAction, useData } from '../lib.jsx';
import { Badge, Button, Card, PageHeader, Table } from '../ui.jsx';

const TYPES = { leave: 'Leave', regularisation: 'Attendance fix', ot: 'Overtime', change_request: 'Detail change', fnf: 'F&F', payroll: 'Payroll', increment: 'Increment' };

export default function Approvals() {
  const { data, reload } = useData('/approvals');
  const [type, setType] = useState('');
  const [run, busy] = useAction();
  const act = (i, approve) => {
    const call = {
      leave: () => api.post(`/leave/requests/${i.id}/decide?approve=${approve}`),
      regularisation: () => api.post(`/regularisations/${i.id}/decide?approve=${approve}`),
      ot: () => api.post(`/attendance/days/${i.id}/ot?approve=${approve}`),
      change_request: () => api.post(`/employees/change-requests/${i.id}/decide`, { approve }),
      increment: () => api.post(`/performance/increments/${i.id}/gm?approve=${approve}`),
    }[i.type];
    return run(call, approve ? 'Approved' : 'Rejected').then((r) => r && reload());
  };
  const open = (i) => (i.type === 'payroll' ? navigate(`/payroll/runs/${i.id}`) : i.type === 'fnf' ? navigate(`/exits/${i.id}`) : i.employee && navigate(`/employees/${i.employee.id}`));
  const items = (data?.items || []).filter((i) => !type || i.type === type);
  const counts = (data?.items || []).reduce((a, i) => ({ ...a, [i.type]: (a[i.type] || 0) + 1 }), {});
  return (
    <div className="stack">
      <PageHeader title="Approvals" sub="Everything waiting for you, in one list." />
      <Card pad={false}>
        <div className="filters"><button className={`chip ${!type ? 'on' : ''}`} onClick={() => setType('')}>All ({data?.count ?? 0})</button>
          {Object.entries(counts).map(([k, n]) => <button key={k} className={`chip ${type === k ? 'on' : ''}`} onClick={() => setType(k)}>{TYPES[k]} ({n})</button>)}</div>
        <Table rows={items} rowKey={(i) => `${i.type}${i.id}`} cols={[{ label: 'Type', render: (i) => <Badge tone="blue">{TYPES[i.type]}</Badge> },
          { label: 'Who', render: (i) => (i.employee ? <div><b>{i.employee.name}</b><div className="muted small">{i.employee.code} · {i.employee.department}</div></div> : '—') },
          { key: 'summary', label: 'Request' }, { key: 'detail', label: 'Detail' }, { label: 'Raised', render: (i) => fmtDate(i.created_at) }, { label: 'Stage', render: (i) => label(i.status) },
          { label: '', render: (i) => (['payroll', 'fnf'].includes(i.type) ? <Button size="s" onClick={() => open(i)}>Open</Button> : <span className="row gap-s">
            <Button size="s" variant="primary" busy={busy} onClick={() => act(i, true)}>Approve</Button>
            <Button size="s" variant="danger" busy={busy} onClick={() => act(i, false)}>Reject</Button></span>) }]} empty="Nothing is waiting for you" />
      </Card>
    </div>
  );
}
