import { useState } from 'react';
import { api, fmtDateTime, label, useAction, useApp, useData } from '../lib.jsx';
import { Badge, Button, Callout, Card, Field, Modal, PageHeader, Table, Tabs } from '../ui.jsx';
import { UserModal } from './Employees.jsx';

export default function Users() {
  const [tab, setTab] = useState('users');
  return (
    <div className="stack">
      <PageHeader title="Users & access" sub="An employee is not a user. Users sign in through Cognito with roles; access is limited by entity and location." />
      <Tabs tabs={[{ id: 'users', label: 'Users' }, { id: 'prov', label: 'Provisioning (sign-in and biometric)' }]} value={tab} onChange={setTab} />
      {tab === 'users' ? <UserList /> : <Provisioning />}
    </div>
  );
}

function UserList() {
  const { setup } = useApp();
  const { data, reload } = useData('/users');
  const { data: roles } = useData('/users/roles');
  const [run, busy] = useAction();
  const [edit, setEdit] = useState(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ roles: [] });
  const [pw, setPw] = useState(null);
  const toggle = (list, v) => (list?.includes(v) ? list.filter((x) => x !== v) : [...(list || []), v]);

  return (
    <>
      <Card title="Users" actions={<Button variant="primary" onClick={() => { setForm({ roles: [] }); setCreating(true); }}>Add user without employee record</Button>} pad={false}>
        <Table rows={data} cols={[
          { label: 'User', render: (u) => <div><b>{u.display_name}</b><div className="muted small">{u.email}</div></div> },
          { label: 'Roles', render: (u) => u.roles.map((r) => roles?.[r] || label(r)).join(', ') },
          { label: 'Scope', render: (u) => <span className="small">{u.entity_scope?.length ? `Entities: ${u.entity_scope.map((id) => setup.entities.find((e) => e.id === id)?.code).join(', ')}` : 'All entities'}
            {u.location_scope?.length ? ` · Locations: ${u.location_scope.map((id) => setup.locations.find((l) => l.id === id)?.code).join(', ')}` : ''}</span> },
          { label: 'Sign-in', render: (u) => <Badge value={u.identity_status || 'pending'} /> },
          { label: 'Status', render: (u) => <Badge tone={u.is_active ? 'green' : 'grey'}>{u.is_active ? 'Active' : 'Inactive'}</Badge> },
          { label: 'Last sign-in', render: (u) => fmtDateTime(u.last_login_at) },
          { label: '', render: (u) => <span className="row gap-s">
            <Button size="s" onClick={() => setEdit({ ...u })}>Edit</Button>
            <Button size="s" busy={busy} onClick={async () => { if (await run(() => api.post(`/users/${u.id}/active?active=${!u.is_active}`), u.is_active ? 'User deactivated' : 'User activated')) reload(); }}>{u.is_active ? 'Deactivate' : 'Activate'}</Button>
            <Button size="s" variant="ghost" busy={busy} onClick={async () => { const r = await run(() => api.post(`/users/${u.id}/reset-password`), 'Password reset'); if (r) setPw({ email: u.email, pw: r.temporary_password }); }}>Reset password</Button></span> },
        ]} />
      </Card>
      <UserModal open={creating} form={form} setForm={setForm} onClose={() => setCreating(false)} onDone={reload} />
      <Modal open={!!edit} title={`Edit ${edit?.email}`} onClose={() => setEdit(null)} wide footer={<Button variant="primary" busy={busy} onClick={async () => {
        const r = await run(() => api.patch(`/users/${edit.id}`, { roles: edit.roles, entity_scope: edit.entity_scope?.length ? edit.entity_scope : [], location_scope: edit.location_scope?.length ? edit.location_scope : [], display_name: edit.display_name }), 'User saved');
        if (r) { setEdit(null); reload(); }
      }}>Save</Button>}>
        {edit && (
          <>
            <Field label="Display name"><input className="input" value={edit.display_name} onChange={(e) => setEdit({ ...edit, display_name: e.target.value })} /></Field>
            <Field group label="Roles"><div className="chips">{Object.entries(roles || {}).map(([k, v]) => <button key={k} type="button" className={`chip ${edit.roles.includes(k) ? 'on' : ''}`} onClick={() => setEdit({ ...edit, roles: toggle(edit.roles, k) })}>{v}</button>)}</div></Field>
            <Field group label="Entities this user can see" hint="None selected = all entities"><div className="chips">{setup.entities.map((e) => <button key={e.id} type="button" className={`chip ${edit.entity_scope?.includes(e.id) ? 'on' : ''}`} onClick={() => setEdit({ ...edit, entity_scope: toggle(edit.entity_scope, e.id) })}>{e.code}</button>)}</div></Field>
            <Field group label="Locations this user can see" hint="None selected = all locations"><div className="chips">{setup.locations.map((l) => <button key={l.id} type="button" className={`chip ${edit.location_scope?.includes(l.id) ? 'on' : ''}`} onClick={() => setEdit({ ...edit, location_scope: toggle(edit.location_scope, l.id) })}>{l.name}</button>)}</div></Field>
            <p className="muted small">Role changes are sent to the sign-in service (Cognito groups) as a provisioning task.</p>
          </>
        )}
      </Modal>
      <Modal open={!!pw} title="Temporary password" onClose={() => setPw(null)}>
        <Callout tone="blue">New temporary password for {pw?.email}: <b className="mono">{pw?.pw}</b>. It is shown only once; the user must change it at sign-in.</Callout>
      </Modal>
    </>
  );
}

function Provisioning() {
  const [status, setStatus] = useState('');
  const { data, reload } = useData(`/users/provisioning${status ? `?status=${status}` : ''}`);
  const [run, busy] = useAction();
  const [pw, setPw] = useState(null);
  return (
    <Card title="Provisioning tasks" actions={<div className="chips">{['', 'failed', 'manual', 'pending', 'done'].map((s) => <button key={s} className={`chip ${status === s ? 'on' : ''}`} onClick={() => setStatus(s)}>{s ? label(s) : 'All'}</button>)}</div>} pad={false}>
      <Callout>Each target has its own status. A failure in one (e.g. the biometric device) never blocks the other. Excel-only biometric: enrol on the device, then confirm here.</Callout>
      <Table rows={data} cols={[
        { label: 'When', render: (t) => fmtDateTime(t.created_at) }, { label: 'Target', render: (t) => (t.target === 'identity' ? 'Sign-in (Cognito)' : 'Biometric device') },
        { label: 'Action', render: (t) => label(t.action) }, { label: 'For', render: (t) => t.user || t.employee || '—' },
        { label: 'Status', render: (t) => <Badge value={t.status} /> }, { key: 'attempts', label: 'Tries', align: 'right' },
        { label: 'Last error', render: (t) => <span className="small red">{t.last_error || ''}</span> },
        { label: '', render: (t) => <span className="row gap-s">
          {t.status === 'failed' && <Button size="s" busy={busy} onClick={async () => { const r = await run(() => api.post(`/users/provisioning/${t.id}/retry`), 'Retried'); if (r) { if (r.temporary_password) setPw(r.temporary_password); reload(); } }}>Retry</Button>}
          {t.status === 'manual' && <Button size="s" variant="primary" busy={busy} onClick={async () => { if (await run(() => api.post(`/users/provisioning/${t.id}/confirm`), 'Enrolment confirmed')) reload(); }}>Confirm enrolled</Button>}</span> },
      ]} empty="No tasks" />
      <Modal open={!!pw} title="Temporary password" onClose={() => setPw(null)}><Callout tone="blue">Temporary password: <b className="mono">{pw}</b></Callout></Modal>
    </Card>
  );
}
