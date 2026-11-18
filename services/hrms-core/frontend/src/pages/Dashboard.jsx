import { fmtDate, Link, navigate, useApp, useData } from '../lib.jsx';
import { Badge, Callout, Card, ErrorBox, Loading, PageHeader, Stat, Table } from '../ui.jsx';

export default function Dashboard() {
  const { me, can } = useApp();
  const { data, error, loading } = useData('/dashboard');
  if (!me.permissions.includes('employees.read')) return <EmployeeHome />;
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  return (
    <div className="stack">
      <PageHeader title={`Good day, ${me.display_name.split(' ')[0]}`} sub="What needs attention today." />
      {!data.missed_punch_rule_set && (
        <Callout tone="amber">The company's missed-punch rule is not set. Payroll will not run while missed punches are open. {can('org.manage') && <Link to="/settings">Set it in Company setup</Link>}</Callout>
      )}
      <Card title="Today">
        <div className="chips">{data.brief.map((b) => <button key={b.label} className="chip" onClick={() => navigate(b.to)}>{b.label}</button>)}</div>
      </Card>
      <div className="grid g4">
        <Stat label="Headcount" value={data.headcount} onClick={() => navigate('/employees')} />
        <Stat label="Present today" value={data.present_today} sub="From processed punches" onClick={() => navigate('/attendance')} />
        <Stat label="Approvals waiting" value={data.pending_approvals} tone={data.pending_approvals ? 'amber' : undefined} onClick={() => navigate('/approvals')} />
        <Stat label="Documents expiring" value={data.documents_expiring} tone={data.documents_expiring ? 'amber' : undefined} onClick={() => navigate('/employees?expiring=1')} />
      </div>
      <div className="grid g2">
        <Card title="Headcount by location" pad={false}>
          <Table cols={[{ key: 'location', label: 'Location' }, { key: 'count', label: 'Staff', align: 'right' }]} rows={data.headcount_by_location} rowKey={(r) => r.location} />
        </Card>
        <Card title="Recent payroll runs" pad={false}>
          <Table cols={[{ key: 'period', label: 'Period' }, { key: 'entity', label: 'Entity' }, { label: 'Status', render: (r) => <Badge value={r.status} /> }]}
            rows={data.payroll_runs} onRow={(r) => navigate(`/payroll/runs/${r.id}`)} empty="No payroll runs yet" />
        </Card>
      </div>
      {data.exits.length > 0 && (
        <Card title="Open exits" pad={false}>
          <Table cols={[{ key: 'employee', label: 'Employee' }, { label: 'Last day', render: (r) => fmtDate(r.last_working_day) }, { label: 'Status', render: (r) => <Badge value={r.status} /> }]}
            rows={data.exits} onRow={(r) => navigate(`/exits/${r.id}`)} />
        </Card>
      )}
    </div>
  );
}

function EmployeeHome() {
  const { me } = useApp();
  return (
    <div className="stack">
      <PageHeader title={`Hello, ${me.display_name.split(' ')[0]}`} sub="Your payslips, leave, attendance and requests are in My HR." />
      <div className="grid g3">
        <Stat label="Payslips" value="View" onClick={() => navigate('/me?tab=payslips')} />
        <Stat label="Leave" value="Apply" onClick={() => navigate('/me?tab=leave')} />
        <Stat label="Attendance" value="This month" onClick={() => navigate('/me?tab=attendance')} />
      </div>
    </div>
  );
}
