import { useState } from 'react';
import { Link, navigate, useApp, useRoute } from './lib.jsx';
import { Loading } from './ui.jsx';
import Login from './pages/Login.jsx';
import Dashboard from './pages/Dashboard.jsx';
import { EmployeeDetail, EmployeeList, EmployeeNew } from './pages/Employees.jsx';
import Imports from './pages/Imports.jsx';
import Users from './pages/Users.jsx';
import Attendance from './pages/Attendance.jsx';
import Leave from './pages/Leave.jsx';
import { PayrollHome, PayrollRun } from './pages/Payroll.jsx';
import Statutory from './pages/Statutory.jsx';
import { ExitDetail, Exits } from './pages/Exits.jsx';
import Performance from './pages/Performance.jsx';
import Reports from './pages/Reports.jsx';
import Comms from './pages/Comms.jsx';
import Approvals from './pages/Approvals.jsx';
import Audit from './pages/Audit.jsx';
import Settings from './pages/Settings.jsx';
import Me from './pages/Me.jsx';

// Menu: shown only when the user's role has the permission (the API enforces it too).
const NAV = [
  { group: 'Overview', items: [{ to: '/', label: 'Dashboard' }, { to: '/approvals', label: 'Approvals', perm: 'employees.read' }] },
  { group: 'People', items: [
    { to: '/employees', label: 'Employees', perm: 'employees.read' },
    { to: '/employees/new', label: 'Onboard employee', perm: 'employees.write' },
    { to: '/imports', label: 'Import from Excel', perm: 'employees.import' },
    { to: '/users', label: 'Users & access', perm: 'users.manage' },
  ] },
  { group: 'Time', items: [{ to: '/attendance', label: 'Attendance', perm: 'attendance.read' }, { to: '/leave', label: 'Leave', perm: 'leave.approve' }] },
  { group: 'Pay', items: [{ to: '/payroll', label: 'Payroll', perm: 'payroll.read' }, { to: '/statutory', label: 'Statutory', perm: 'statutory.manage' }] },
  { group: 'Lifecycle', items: [
    { to: '/exits', label: 'Exits & F&F', perm: 'exits.manage' },
    { to: '/performance', label: 'Performance', perm: 'performance.review' },
    { to: '/circulars', label: 'Circulars', perm: 'comms.send' },
  ] },
  { group: 'Insight', items: [{ to: '/reports', label: 'Reports', perm: 'reports.read' }, { to: '/audit', label: 'Audit trail', perm: 'audit.read' }] },
  { group: 'Me', items: [{ to: '/me', label: 'My HR', needsEmployee: true }] },
  { group: 'Setup', items: [{ to: '/settings', label: 'Company setup', perm: 'org.manage' }] },
];

function route(path) {
  const seg = path.split('/').filter(Boolean);
  if (path === '/') return <Dashboard />;
  if (seg[0] === 'employees') {
    if (seg[1] === 'new') return <EmployeeNew />;
    if (seg[1]) return <EmployeeDetail id={seg[1]} />;
    return <EmployeeList />;
  }
  if (seg[0] === 'payroll' && seg[1] === 'runs' && seg[2]) return <PayrollRun id={seg[2]} />;
  if (seg[0] === 'exits' && seg[1]) return <ExitDetail id={seg[1]} />;
  const pages = { imports: Imports, users: Users, attendance: Attendance, leave: Leave, payroll: PayrollHome, statutory: Statutory, exits: Exits,
    performance: Performance, reports: Reports, circulars: Comms, approvals: Approvals, audit: Audit, settings: Settings, me: Me };
  const P = pages[seg[0]];
  return P ? <P /> : <div className="empty-page"><h2>Page not found</h2><Link to="/">Back to dashboard</Link></div>;
}

export default function App() {
  const { me, loading, signOut } = useApp();
  const { path } = useRoute();
  const [open, setOpen] = useState(false);

  if (loading) return <div className="center-page"><Loading what="Starting" /></div>;
  if (!me || path === '/login') {
    if (me && path === '/login') { navigate('/'); return null; }
    return <Login />;
  }
  const can = (p) => !p || me.permissions.includes(p);
  const active = (to) => (to === '/' ? path === '/' : path === to || path.startsWith(`${to}/`)) && !(to === '/employees' && path === '/employees/new');

  return (
    <div className="app">
      <aside className={`side ${open ? 'open' : ''}`}>
        <div className="brand"><span className="logo">HR</span><div><b>Peak HRMS</b><div className="muted small">{me.company}</div></div></div>
        <nav>
          {NAV.map((g) => {
            const items = g.items.filter((i) => can(i.perm) && (!i.needsEmployee || me.employee_id));
            if (!items.length) return null;
            return (
              <div key={g.group} className="nav-group">
                <div className="nav-gl">{g.group}</div>
                {items.map((i) => <Link key={i.to} to={i.to} className={`nav-item ${active(i.to) ? 'on' : ''}`} onClick={() => setOpen(false)}>{i.label}</Link>)}
              </div>
            );
          })}
        </nav>
      </aside>
      {open && <div className="scrim" onClick={() => setOpen(false)} />}
      <div className="body">
        <header className="top">
          <button className="icon-btn burger" onClick={() => setOpen(true)} aria-label="Open menu">☰</button>
          <div className="grow" />
          <div className="who"><b>{me.display_name}</b><span className="muted small">{me.role_labels.join(', ')}</span></div>
          <button className="btn btn-ghost btn-s" onClick={signOut}>Sign out</button>
        </header>
        <main className="main" key={path}>{route(path)}</main>
      </div>
    </div>
  );
}
