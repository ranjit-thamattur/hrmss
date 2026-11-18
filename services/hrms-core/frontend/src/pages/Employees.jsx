import { useState } from 'react';
import { api, fmtDate, fmtDateTime, label, Link, money, navigate, qs, today, useAction, useApp, useData, useRoute } from '../lib.jsx';
import tenant from '@tenant/tenant.js';
import { Badge, Button, Callout, Card, ErrorBox, Field, Loading, Modal, PageHeader, Pager, Select, Table, Tabs, useForm } from '../ui.jsx';

export function EmployeeList() {
  const { setup } = useApp();
  const { search } = useRoute();
  const [f, setF] = useState({ q: '', entity_id: '', location_id: '', department_id: '', status: '', expiring: search.get('expiring') ? 'true' : '', page: 1 });
  const { data, error, loading } = useData(`/employees${qs({ ...f, size: 25 })}`);
  const set = (k, v) => setF({ ...f, [k]: v, page: k === 'page' ? v : 1 });
  const opt = (rows, l = 'name') => rows.map((r) => ({ value: r.id, label: r[l] }));
  return (
    <div className="stack">
      <PageHeader title="Employees" sub="Everyone on the employee master across all entities and locations." actions={<>
        <Button onClick={() => navigate('/imports')}>Import from Excel</Button>
        <Button variant="primary" onClick={() => navigate('/employees/new')}>Onboard employee</Button></>} />
      <Card pad={false}>
        <div className="filters">
          <input className="input input-s" placeholder="Search name, code, phone" value={f.q} onChange={(e) => set('q', e.target.value)} style={{ minWidth: 220 }} />
          <Select className="input input-s" value={f.entity_id} onChange={(v) => set('entity_id', v)} options={opt(setup.entities)} placeholder="All entities" />
          <Select className="input input-s" value={f.location_id} onChange={(v) => set('location_id', v)} options={opt(setup.locations)} placeholder="All locations" />
          <Select className="input input-s" value={f.department_id} onChange={(v) => set('department_id', v)} options={opt(setup.departments)} placeholder="All departments" />
          <Select className="input input-s" value={f.status} onChange={(v) => set('status', v)} options={['active', 'notice', 'exited']} placeholder="Active + notice" />
          <label className="check small"><input type="checkbox" checked={!!f.expiring} onChange={(e) => set('expiring', e.target.checked ? 'true' : '')} /> Documents expiring</label>
        </div>
        <ErrorBox error={error} />
        {loading && !data ? <Loading /> : (
          <>
            <Table rows={data?.items} onRow={(r) => navigate(`/employees/${r.id}`)} cols={[
              { label: 'Employee', render: (r) => <div><b>{r.name}</b><div className="muted small">{r.code} · {r.designation || '—'}</div></div> },
              { key: 'entity', label: 'Entity' }, { key: 'location', label: 'Location' }, { key: 'department', label: 'Department' }, { key: 'grade', label: 'Grade' },
              { label: 'Status', render: (r) => <Badge value={r.status} /> },
              { label: 'Flags', render: (r) => <span className="row gap-s">{r.doc_expiring && <Badge tone="amber">Doc</Badge>}{!r.has_bank && <Badge tone="red">No bank</Badge>}
                {r.change_pending && <Badge tone="blue">Change</Badge>}{r.has_user && <Badge tone="green">User</Badge>}</span> },
            ]} />
            <Pager page={f.page} size={25} total={data?.total || 0} onPage={(p) => set('page', p)} />
          </>
        )}
      </Card>
    </div>
  );
}

const LANGS = tenant.languages.map((l) => ({ value: l.code, label: l.label }));

const EMPTY = { code: '', first_name: '', last_name: '', gender: '', dob: '', doj: today(), phone: '', email: '', language: tenant.defaultLanguage, location_id: '', department_id: '',
  designation_id: '', grade_id: '', manager_id: '', shift_code: 'G', pan: '', aadhaar: '', bank_account: '', ifsc: '', bank_name: '', uan: '', esic_no: '', monthly_gross: '' };

export function EmployeeNew() {
  const { setup } = useApp();
  const [v, , bind] = useForm(EMPTY);
  const [run, busy] = useAction();
  const opt = (rows, l = 'name') => rows.map((r) => ({ value: r.id, label: r[l] }));
  const submit = async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(Object.entries(v).filter(([, x]) => x !== ''));
    for (const k of ['location_id', 'department_id', 'designation_id', 'grade_id', 'manager_id']) if (body[k]) body[k] = Number(body[k]);
    const r = await run(() => api.post('/employees', body), 'Employee added');
    if (r) navigate(`/employees/${r.id}`);
  };
  const sel = (k, rows, l) => <Select value={v[k]} onChange={(x) => bind(k).onChange({ target: { value: x } })} options={opt(rows, l)} placeholder="Choose" />;
  return (
    <form className="stack" onSubmit={submit}>
      <PageHeader title="Onboard employee" sub="Adds the person to the employee master and enrols them on the biometric device. Software access is a separate step (Users & access)." />
      <Card title="Person">
        <div className="grid g3">
          <Field label="Employee code"><input className="input" {...bind('code')} required /></Field>
          <Field label="First name"><input className="input" {...bind('first_name')} required /></Field>
          <Field label="Last name"><input className="input" {...bind('last_name')} /></Field>
          <Field label="Gender"><Select value={v.gender} onChange={(x) => bind('gender').onChange({ target: { value: x } })} options={['F', 'M', 'Other']} placeholder="—" /></Field>
          <Field label="Date of birth"><input className="input" type="date" {...bind('dob')} /></Field>
          <Field label="Mobile (WhatsApp)"><input className="input" {...bind('phone')} /></Field>
          <Field label="Email"><input className="input" type="email" {...bind('email')} /></Field>
          <Field label="Language"><Select value={v.language} onChange={(x) => bind('language').onChange({ target: { value: x } })} options={LANGS} /></Field>
        </div>
      </Card>
      <Card title="Job">
        <div className="grid g3">
          <Field label="Date of joining"><input className="input" type="date" {...bind('doj')} required /></Field>
          <Field label="Location">{sel('location_id', setup.locations)}</Field>
          <Field label="Department">{sel('department_id', setup.departments)}</Field>
          <Field label="Designation">{sel('designation_id', setup.designations)}</Field>
          <Field label="Grade">{sel('grade_id', setup.grades, 'code')}</Field>
          <Field label="Default shift"><Select value={v.shift_code} onChange={(x) => bind('shift_code').onChange({ target: { value: x } })} options={setup.shifts.map((s) => ({ value: s.code, label: `${s.code} · ${s.name}` }))} /></Field>
          <Field label="Monthly gross (₹)" hint="Split Basic 50%, HRA 20%, Conveyance 1,600, rest Special; edit later"><input className="input" type="number" {...bind('monthly_gross')} /></Field>
        </div>
      </Card>
      <Card title="Statutory and bank">
        <div className="grid g3">
          <Field label="PAN"><input className="input" {...bind('pan')} placeholder="ABCDE1234F" /></Field>
          <Field label="Aadhaar" hint="Only the last 4 digits are stored"><input className="input" {...bind('aadhaar')} /></Field>
          <Field label="UAN (EPF)"><input className="input" {...bind('uan')} /></Field>
          <Field label="ESI IP number"><input className="input" {...bind('esic_no')} /></Field>
          <Field label="Bank account"><input className="input" {...bind('bank_account')} /></Field>
          <Field label="IFSC"><input className="input" {...bind('ifsc')} /></Field>
        </div>
      </Card>
      <div className="row gap-s"><Button variant="primary" type="submit" busy={busy}>Add employee</Button><Button variant="ghost" type="button" onClick={() => navigate('/employees')}>Cancel</Button></div>
    </form>
  );
}

export function EmployeeDetail({ id }) {
  const { can, setup } = useApp();
  const { data: e, error, loading, reload } = useData(`/employees/${id}`);
  const [tab, setTab] = useState('profile');
  const [run, busy] = useAction();
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState({});
  if (loading && !e) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const edit = can('employees.write');
  const save = async (path, body, msg, method = 'post') => { if (await run(() => api[method](path, body), msg)) { setModal(null); reload(); } };
  const tabs = [{ id: 'profile', label: 'Profile' }, { id: 'pay', label: 'Pay' }, { id: 'docs', label: 'Documents', count: e.documents.length },
    { id: 'changes', label: 'Change requests', count: e.change_requests.filter((c) => c.status === 'pending').length }, ...(can('audit.read') ? [{ id: 'timeline', label: 'Timeline' }] : [])];
  return (
    <div className="stack">
      <PageHeader title={e.name} sub={`${e.code} · ${e.designation || '—'} · ${e.location} · ${e.entity} · joined ${fmtDate(e.doj)}`} actions={<>
        <Badge value={e.status} />
        {can('users.manage') && !e.user && <Button variant="primary" onClick={() => { setForm({ email: e.email || '', roles: ['employee'] }); setModal('user'); }}>Give software access</Button>}
        {e.user && <Badge tone="green">User: {e.user.email}</Badge>}
        {can('exits.manage') && e.status === 'active' && <Button onClick={() => { setForm({ resigned_on: today(), reason: '' }); setModal('exit'); }}>Record resignation</Button>}</>} />
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === 'profile' && (
        <div className="grid g2">
          <Card title="Personal" actions={edit && <Button size="s" onClick={() => { setForm({ phone: e.phone || '', email: e.email || '', language: e.language, shift_code: e.shift_code }); setModal('edit'); }}>Edit</Button>}>
            <dl className="kv">
              <dt>Mobile</dt><dd>{e.phone || '—'}</dd><dt>Email</dt><dd>{e.email || '—'}</dd><dt>Date of birth</dt><dd>{fmtDate(e.dob)}</dd>
              <dt>Language</dt><dd>{LANGS.find((l) => l.value === e.language)?.label || e.language}</dd><dt>Manager / HOD</dt><dd>{e.manager || '—'}</dd><dt>Shift</dt><dd>{e.shift_code}</dd>
              <dt>Biometric ID</dt><dd>{e.biometric_id || '—'}</dd>
            </dl>
          </Card>
          <Card title="Statutory and bank">
            {!e.can_see_sensitive && <Callout>Sensitive fields are masked for your role.</Callout>}
            <dl className="kv mt">
              <dt>PAN</dt><dd className="mono">{e.pan || '—'}</dd><dt>Aadhaar</dt><dd className="mono">{e.aadhaar || '—'}</dd><dt>UAN</dt><dd className="mono">{e.uan || '—'}</dd>
              <dt>ESI IP</dt><dd className="mono">{e.esic_no || 'Not covered'}</dd><dt>Bank</dt><dd className="mono">{e.bank_account || <span className="red">Missing</span>} {e.ifsc}</dd>
              <dt>PF / ESI / PT / LWF</dt><dd>{[e.pf_applicable, e.esi_applicable, e.pt_applicable, e.lwf_applicable].map((x) => (x ? 'Yes' : 'No')).join(' / ')}</dd>
            </dl>
          </Card>
        </div>
      )}
      {tab === 'pay' && (
        <div className="grid g2">
          <Card title="Salary structure" actions={edit && <Button size="s" onClick={() => { setForm({ effective_from: today(), BASIC: '', HRA: '', CONV: '', SPECIAL: '' }); setModal('salary'); }}>New version</Button>}>
            {e.salary ? (
              <>
                <p className="muted small">In force from {fmtDate(e.salary.effective_from)} · source: {e.salary.source}</p>
                <Table cols={[{ key: 'k', label: 'Component' }, { label: 'Monthly', align: 'right', render: (r) => money(r.v) }]}
                  rows={Object.entries(e.salary.components).map(([k, v]) => ({ k, v }))} rowKey={(r) => r.k} />
                <p className="mt"><b>Gross {money(e.salary.monthly_gross)}</b></p>
              </>
            ) : <p className="muted">{e.can_see_sensitive ? 'No salary structure yet.' : 'Not visible for your role.'}</p>}
          </Card>
          <Card title="Paying entities" actions={edit && <Button size="s" onClick={() => { setForm({ effective_from: today(), parts: [{ entity_id: setup.entities[0].id, method: 'percent', value: 100, is_primary: true }] }); setModal('alloc'); }}>Change</Button>}>
            <Table cols={[{ label: 'Entity', render: (a) => setup.entities.find((x) => x.id === a.entity_id)?.code }, { label: 'Share', render: (a) => (a.method === 'percent' ? `${Number(a.value)}%` : money(a.value)) },
              { label: 'Primary', render: (a) => (a.is_primary ? 'Yes' : '') }, { label: 'From', render: (a) => fmtDate(a.effective_from) }, { label: 'To', render: (a) => fmtDate(a.effective_to) }]} rows={e.allocations} />
          </Card>
        </div>
      )}
      {tab === 'docs' && (
        <Card title="Documents" actions={edit && <Button size="s" onClick={() => { setForm({ doc_type: '', expiry_date: '', number: '' }); setModal('doc'); }}>Add document</Button>} pad={false}>
          <Table cols={[{ key: 'doc_type', label: 'Document' }, { key: 'number_masked', label: 'Number' }, { label: 'Expiry', render: (d) => fmtDate(d.expiry_date) },
            { label: 'File', render: (d) => (d.file_key ? <button className="link btn-ghost btn" onClick={() => api.download(`/employees/${e.id}/documents/${d.id}/file`)}>Download</button> : '—') }]} rows={e.documents} empty="No documents" />
        </Card>
      )}
      {tab === 'changes' && (
        <Card title="Change requests" pad={false}>
          <Table cols={[{ label: 'Field', render: (c) => label(c.field) }, { label: 'Requested', render: (c) => fmtDateTime(c.created_at) }, { key: 'reason', label: 'Reason' },
            { label: 'Status', render: (c) => <Badge value={c.status} /> },
            { label: '', render: (c) => edit && c.status === 'pending' && <span className="row gap-s">
              <Button size="s" variant="primary" busy={busy} onClick={() => save(`/employees/change-requests/${c.id}/decide`, { approve: true }, 'Change approved')}>Approve</Button>
              <Button size="s" variant="danger" busy={busy} onClick={() => save(`/employees/change-requests/${c.id}/decide`, { approve: false }, 'Change rejected')}>Reject</Button></span> }]}
          rows={e.change_requests} empty="No change requests" />
        </Card>
      )}
      {tab === 'timeline' && <Timeline id={e.id} />}

      <Modal open={modal === 'edit'} title="Edit employee" onClose={() => setModal(null)} footer={<Button variant="primary" busy={busy} onClick={() => save(`/employees/${e.id}`, form, 'Saved', 'patch')}>Save</Button>}>
        <Field label="Mobile"><input className="input" value={form.phone || ''} onChange={(x) => setForm({ ...form, phone: x.target.value })} /></Field>
        <Field label="Email"><input className="input" value={form.email || ''} onChange={(x) => setForm({ ...form, email: x.target.value })} /></Field>
        <Field label="Language"><Select value={form.language} onChange={(x) => setForm({ ...form, language: x })} options={LANGS} /></Field>
        <Field label="Default shift"><Select value={form.shift_code} onChange={(x) => setForm({ ...form, shift_code: x })} options={setup.shifts.map((s) => s.code)} /></Field>
      </Modal>
      <Modal open={modal === 'salary'} title="New salary structure" onClose={() => setModal(null)} footer={<Button variant="primary" busy={busy}
        onClick={() => save(`/employees/${e.id}/salary`, { effective_from: form.effective_from, components: Object.fromEntries(['BASIC', 'DA', 'HRA', 'CONV', 'SPECIAL'].filter((k) => form[k]).map((k) => [k, form[k]])) }, 'Salary structure saved')}>Save</Button>}>
        <Field label="Effective from" hint="The current version ends the day before"><input className="input" type="date" value={form.effective_from || ''} onChange={(x) => setForm({ ...form, effective_from: x.target.value })} /></Field>
        <div className="grid g2">{['BASIC', 'DA', 'HRA', 'CONV', 'SPECIAL'].map((k) => <Field key={k} label={k}><input className="input" type="number" value={form[k] || ''} onChange={(x) => setForm({ ...form, [k]: x.target.value })} /></Field>)}</div>
      </Modal>
      <Modal open={modal === 'alloc'} title="Paying entities (split salary)" onClose={() => setModal(null)} wide footer={<Button variant="primary" busy={busy}
        onClick={() => save(`/employees/${e.id}/allocations`, { effective_from: form.effective_from, parts: form.parts.map((p) => ({ ...p, entity_id: Number(p.entity_id), value: Number(p.value) })) }, 'Paying entities saved')}>Save</Button>}>
        <Field label="Effective from"><input className="input" type="date" value={form.effective_from || ''} onChange={(x) => setForm({ ...form, effective_from: x.target.value })} /></Field>
        {(form.parts || []).map((p, i) => (
          <div key={i} className="row gap-s">
            <Select value={p.entity_id} onChange={(x) => { const parts = [...form.parts]; parts[i] = { ...p, entity_id: x }; setForm({ ...form, parts }); }} options={setup.entities.map((x) => ({ value: x.id, label: x.code }))} />
            <Select value={p.method} onChange={(x) => { const parts = [...form.parts]; parts[i] = { ...p, method: x }; setForm({ ...form, parts }); }} options={[{ value: 'percent', label: '% of pay' }, { value: 'fixed', label: 'Fixed ₹' }]} />
            <input className="input" type="number" value={p.value} onChange={(x) => { const parts = [...form.parts]; parts[i] = { ...p, value: x.target.value }; setForm({ ...form, parts }); }} />
            <label className="check small"><input type="radio" checked={!!p.is_primary} onChange={() => setForm({ ...form, parts: form.parts.map((q, j) => ({ ...q, is_primary: i === j })) })} /> Primary</label>
          </div>
        ))}
        <Button size="s" onClick={() => setForm({ ...form, parts: [...form.parts, { entity_id: setup.entities[0].id, method: 'percent', value: 0, is_primary: false }] })}>Add entity</Button>
      </Modal>
      <Modal open={modal === 'doc'} title="Add document" onClose={() => setModal(null)} footer={<Button variant="primary" busy={busy} onClick={async () => {
        const fd = new FormData();
        fd.append('doc_type', form.doc_type); if (form.expiry_date) fd.append('expiry_date', form.expiry_date); if (form.number) fd.append('number', form.number);
        if (form.file) fd.append('file', form.file);
        if (await run(() => api.upload(`/employees/${e.id}/documents`, fd), 'Document added')) { setModal(null); reload(); }
      }}>Save</Button>}>
        <Field label="Type"><input className="input" value={form.doc_type || ''} onChange={(x) => setForm({ ...form, doc_type: x.target.value })} placeholder="e.g. Police verification" /></Field>
        <Field label="Number" hint="Stored masked"><input className="input" value={form.number || ''} onChange={(x) => setForm({ ...form, number: x.target.value })} /></Field>
        <Field label="Expiry date"><input className="input" type="date" value={form.expiry_date || ''} onChange={(x) => setForm({ ...form, expiry_date: x.target.value })} /></Field>
        <Field label="File"><input type="file" onChange={(x) => setForm({ ...form, file: x.target.files?.[0] })} /></Field>
      </Modal>
      <UserModal open={modal === 'user'} employee={e} form={form} setForm={setForm} onClose={() => setModal(null)} onDone={reload} />
      <Modal open={modal === 'exit'} title="Record resignation" onClose={() => setModal(null)} footer={<Button variant="primary" busy={busy} onClick={async () => {
        const r = await run(() => api.post('/exits', { employee_id: e.id, ...form }), 'Resignation recorded');
        if (r) navigate(`/exits/${r.id}`);
      }}>Save</Button>}>
        <Field label="Resigned on"><input className="input" type="date" value={form.resigned_on || ''} onChange={(x) => setForm({ ...form, resigned_on: x.target.value })} /></Field>
        <Field label="Last working day" hint="Leave empty to set it from the notice period"><input className="input" type="date" value={form.last_working_day || ''} onChange={(x) => setForm({ ...form, last_working_day: x.target.value })} /></Field>
        <Field label="Reason"><textarea className="input" rows={2} value={form.reason || ''} onChange={(x) => setForm({ ...form, reason: x.target.value })} /></Field>
      </Modal>
    </div>
  );
}

export function UserModal({ open, employee, form, setForm, onClose, onDone }) {
  const [run, busy] = useAction();
  const { data: roles } = useData(open ? '/users/roles' : null);
  const [result, setResult] = useState(null);
  const close = () => { setResult(null); onClose(); };
  return (
    <Modal open={open} title={`Software access${employee ? ` · ${employee.name}` : ''}`} onClose={close} footer={!result && <Button variant="primary" busy={busy} onClick={async () => {
      const r = await run(() => api.post('/users', { ...form, employee_id: employee?.id }), 'User created');
      if (r) { setResult(r); onDone?.(); }
    }}>Create user</Button>}>
      {result ? (
        <div className="stack">
          <Callout tone={result.identity_status === 'done' ? 'green' : 'red'}>Sign-in account: <b>{result.identity_status}</b>{result.identity_error ? ` — ${result.identity_error}` : ''}</Callout>
          {result.temporary_password && <Callout tone="blue">Temporary password (shown once): <b className="mono">{result.temporary_password}</b>. The person sets their own at first sign-in.</Callout>}
          <Button onClick={close}>Done</Button>
        </div>
      ) : (
        <>
          <Field label="Sign-in email"><input className="input" type="email" value={form.email || ''} onChange={(x) => setForm({ ...form, email: x.target.value })} /></Field>
          {!employee && <Field label="Display name"><input className="input" value={form.display_name || ''} onChange={(x) => setForm({ ...form, display_name: x.target.value })} /></Field>}
          <Field group label="Roles">
            <div className="chips">{Object.entries(roles || {}).map(([k, v]) => (
              <button type="button" key={k} className={`chip ${form.roles?.includes(k) ? 'on' : ''}`}
                onClick={() => setForm({ ...form, roles: form.roles?.includes(k) ? form.roles.filter((x) => x !== k) : [...(form.roles || []), k] })}>{v}</button>))}</div>
          </Field>
          <p className="muted small">The user is created in the sign-in service (Cognito) with these roles. Employee records alone never give access.</p>
        </>
      )}
    </Modal>
  );
}

function Timeline({ id }) {
  const { data, loading } = useData(`/employees/${id}/timeline`);
  if (loading || !data) return <Loading />;
  return (
    <div className="grid g2">
      <Card title="Assignments" pad={false}>
        <Table cols={[{ label: 'From', render: (a) => fmtDate(a.effective_from) }, { label: 'To', render: (a) => fmtDate(a.effective_to) }, { key: 'location', label: 'Location' }, { key: 'department', label: 'Department' }]} rows={data.assignments} />
      </Card>
      <Card title="Audit trail (cannot be edited)" pad={false}>
        <Table cols={[{ label: 'When', render: (a) => fmtDateTime(a.at) }, { key: 'actor', label: 'Who' }, { label: 'What', render: (a) => <div><b>{label(a.action)}</b>
          {a.after && <div className="muted small mono">{JSON.stringify(a.after).slice(0, 160)}</div>}</div> }]} rows={[...data.events].reverse()} />
      </Card>
    </div>
  );
}

export { Link };
