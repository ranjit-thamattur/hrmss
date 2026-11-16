import { useState } from 'react';
import { api, fmtDate, fmtDateTime, label, today, useAction, useApp, useData } from '../lib.jsx';
import { Badge, Button, Callout, Card, Field, Modal, PageHeader, Select, Table, Tabs } from '../ui.jsx';

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

// Column definitions for each setup table: [key, label, type]
const TABLES = {
  entities: { title: 'Entities', key: 'id', cols: [['code', 'Code'], ['name', 'Legal name'], ['state', 'State'], ['pan', 'PAN'], ['tan', 'TAN'], ['pf_code', 'EPF code'], ['esi_code', 'ESI code'], ['tally_company', 'Tally company'], ['is_active', 'Active', 'bool']] },
  locations: { title: 'Locations', key: 'id', cols: [['code', 'Code'], ['name', 'Name'], ['entity_id', 'Entity', 'entity'], ['state', 'State'], ['weekly_off', 'Weekly off', 'weekday'], ['is_active', 'Active', 'bool']] },
  departments: { title: 'Departments', key: 'id', cols: [['name', 'Name']] },
  designations: { title: 'Designations', key: 'id', cols: [['name', 'Name']] },
  grades: { title: 'Grades', key: 'id', cols: [['code', 'Code'], ['name', 'Name'], ['min_gross', 'Min gross', 'number'], ['max_gross', 'Max gross', 'number'], ['notice_days', 'Notice days', 'number']] },
  shifts: { title: 'Shifts', key: 'id', cols: [['code', 'Code'], ['name', 'Name'], ['start_time', 'Start', 'time'], ['end_time', 'End', 'time'], ['break_minutes', 'Break (min)', 'number'], ['is_night', 'Night', 'bool'], ['is_off', 'Off day', 'bool']] },
  holidays: { title: 'Holidays', key: 'id', cols: [['day', 'Date', 'date'], ['name', 'Name'], ['location_id', 'Location (empty = all)', 'location']] },
  'leave-types': { title: 'Leave types', key: 'code', cols: [['code', 'Code'], ['name', 'Name'], ['annual_quota', 'Days per year', 'number'], ['paid', 'Paid', 'bool']] },
};

export default function Settings() {
  const [tab, setTab] = useState('policies');
  return (
    <div className="stack">
      <PageHeader title="Company setup" sub="Masters, dated policies and versioned statutory rules. Every change is recorded in the audit trail." />
      <Tabs tabs={[{ id: 'policies', label: 'Policies' }, { id: 'rules', label: 'Statutory rules' }, ...Object.entries(TABLES).map(([id, t]) => ({ id, label: t.title }))]} value={tab} onChange={setTab} />
      {tab === 'policies' && <Policies />}
      {tab === 'rules' && <Rules />}
      {TABLES[tab] && <SetupTable key={tab} kind={tab} />}
    </div>
  );
}

function SetupTable({ kind }) {
  const { setup, reloadSetup } = useApp();
  const t = TABLES[kind];
  const { data, reload } = useData(`/org/tables/${kind}`);
  const [edit, setEdit] = useState(null);
  const [run, busy] = useAction();
  const show = (c, r) => {
    const v = r[c[0]];
    if (c[2] === 'bool') return v ? 'Yes' : 'No';
    if (c[2] === 'entity') return setup.entities.find((e) => e.id === v)?.code;
    if (c[2] === 'location') return v ? setup.locations.find((l) => l.id === v)?.name : 'All';
    if (c[2] === 'weekday') return DAYS[v];
    if (c[2] === 'date') return fmtDate(v);
    return v ?? '—';
  };
  const input = (c) => {
    const [k, , type] = c;
    const v = edit[k];
    const set = (x) => setEdit({ ...edit, [k]: x });
    if (type === 'bool') return <label className="check"><input type="checkbox" checked={!!v} onChange={(e) => set(e.target.checked)} /> Yes</label>;
    if (type === 'entity') return <Select value={v} onChange={(x) => set(Number(x))} options={setup.entities.map((e) => ({ value: e.id, label: e.code }))} placeholder="Choose" />;
    if (type === 'location') return <Select value={v ?? ''} onChange={(x) => set(x ? Number(x) : null)} options={setup.locations.map((l) => ({ value: l.id, label: l.name }))} placeholder="All locations" />;
    if (type === 'weekday') return <Select value={v} onChange={(x) => set(Number(x))} options={DAYS.map((d, i) => ({ value: i, label: d }))} />;
    return <input className="input" type={type || 'text'} value={v ?? ''} onChange={(e) => set(type === 'number' ? e.target.value : e.target.value)} />;
  };
  const save = async () => {
    const isNew = edit.__new;
    const body = { ...edit };
    delete body.__new;
    const r = await run(() => (isNew ? api.post(`/org/tables/${kind}`, body) : api.put(`/org/tables/${kind}/${edit[t.key]}`, body)), 'Saved');
    if (r) { setEdit(null); reload(); reloadSetup(); }
  };
  const remove = async () => {
    if (await run(() => api.del(`/org/tables/${kind}/${edit[t.key]}`), 'Deleted')) { setEdit(null); reload(); reloadSetup(); }
  };
  return (
    <Card title={t.title} actions={<Button variant="primary" onClick={() => setEdit({ __new: true })}>Add</Button>} pad={false}>
      <Table rows={data} rowKey={(r) => r[t.key]} onRow={(r) => setEdit({ ...r })} cols={t.cols.map((c) => ({ key: c[0], label: c[1], render: (r) => show(c, r) }))} />
      <Modal open={!!edit} title={edit?.__new ? `Add to ${t.title}` : `Edit ${t.title}`} onClose={() => setEdit(null)} footer={<>
        {!edit?.__new && !['entities', 'locations', 'departments'].includes(kind) && <Button variant="danger" busy={busy} onClick={remove}>Delete</Button>}
        <Button variant="primary" busy={busy} onClick={save}>Save</Button></>}>
        {edit && <div className="grid g2">{t.cols.map((c) => (kind === 'leave-types' && c[0] === 'code' && !edit.__new ? null : <Field key={c[0]} label={c[1]}>{input(c)}</Field>))}</div>}
        {kind === 'entities' && <p className="muted small">Entities, locations and departments are set inactive rather than deleted, so history stays intact.</p>}
      </Modal>
    </Card>
  );
}

function Policies() {
  const { data, reload } = useData('/org/policies/current');
  const [edit, setEdit] = useState(null);
  const [run, busy] = useAction();
  if (!data) return null;
  const keys = Object.keys(data.help);
  return (
    <>
      {!data.values.missed_punch_rule && <Callout tone="amber">The missed-punch rule has no default on purpose. Hotel Vivek must choose one (present, LOP or hold), or every missed punch must be fixed before payroll can run.</Callout>}
      <Card title="Policies in force today" pad={false}>
        <Table rows={keys.map((k) => ({ k, v: data.values[k] }))} rowKey={(r) => r.k} onRow={(r) => setEdit({ key: r.k, value: r.v ?? '', effective_from: today(), note: '' })} cols={[
          { label: 'Policy', render: (r) => <div><b>{label(r.k)}</b><div className="muted small">{data.help[r.k]}</div></div> },
          { label: 'Value', render: (r) => (r.v === null || r.v === undefined ? <Badge tone="amber">Not set</Badge> : <b>{String(label(String(r.v)))}</b>) }]} />
      </Card>
      <Card title="History (dated versions)" pad={false}>
        <Table rows={data.history} cols={[{ label: 'Policy', render: (h) => label(h.key) }, { label: 'Value', render: (h) => String(h.value) }, { label: 'From', render: (h) => fmtDate(h.effective_from) },
          { key: 'note', label: 'Note' }, { key: 'created_by', label: 'By' }, { label: 'When', render: (h) => fmtDateTime(h.created_at) }]} empty="Only defaults so far" />
      </Card>
      <Modal open={!!edit} title={edit ? label(edit.key) : ''} onClose={() => setEdit(null)} footer={<Button variant="primary" busy={busy} onClick={async () => {
        const value = edit.key === 'missed_punch_rule' ? edit.value || null : Number(edit.value);
        if (await run(() => api.post('/org/policies', { ...edit, value }), 'New policy version saved')) { setEdit(null); reload(); }
      }}>Save new version</Button>}>
        {edit && (
          <>
            <p className="muted">{data.help[edit.key]}</p>
            <Field label="Value">{edit.key === 'missed_punch_rule'
              ? <Select value={edit.value} onChange={(v) => setEdit({ ...edit, value: v })} options={data.missed_punch_options.map((o) => ({ value: o, label: { present: 'Treat as present', lop: 'Loss of pay', hold: 'Hold the day (unpaid until fixed)' }[o] || o }))} placeholder="Not set" />
              : <input className="input" type="number" value={edit.value} onChange={(e) => setEdit({ ...edit, value: e.target.value })} />}</Field>
            <Field label="Effective from" hint="Earlier periods keep the old value"><input className="input" type="date" value={edit.effective_from} onChange={(e) => setEdit({ ...edit, effective_from: e.target.value })} /></Field>
            <Field label="Note (e.g. who decided)"><input className="input" value={edit.note} onChange={(e) => setEdit({ ...edit, note: e.target.value })} /></Field>
          </>
        )}
      </Modal>
    </>
  );
}

function Rules() {
  const { setup } = useApp();
  const { data, reload } = useData('/org/statutory-rules');
  const [text, setText] = useState(null);
  const [meta, setMeta] = useState({ effective_from: today(), entity_id: '', note: '' });
  const [run, busy] = useAction();
  const [err, setErr] = useState('');
  if (!data) return null;
  const save = async () => {
    let rules;
    try { rules = JSON.parse(text); } catch (e) { setErr(`Not valid JSON: ${e.message}`); return; }
    setErr('');
    if (await run(() => api.post('/org/statutory-rules', { rules, effective_from: meta.effective_from, entity_id: meta.entity_id ? Number(meta.entity_id) : null, note: meta.note }), 'Rule version saved')) { setText(null); reload(); }
  };
  return (
    <>
      <Callout tone="amber">Rule version <b>{data.current.version}</b> is in force. Sample values: an auditor must confirm PF, ESI, PT, LWF and TDS figures before live payroll. A new version applies from its date; earlier payroll keeps the old rules.</Callout>
      <Card title="Current rules" actions={<Button variant="primary" onClick={() => setText(JSON.stringify(data.current, null, 2))}>New version</Button>}>
        <pre className="code">{JSON.stringify(data.current, null, 2)}</pre>
      </Card>
      <Card title="Versions" pad={false}>
        <Table rows={data.versions} cols={[{ label: 'From', render: (v) => fmtDate(v.effective_from) }, { label: 'Entity', render: (v) => (v.entity_id ? setup.entities.find((e) => e.id === v.entity_id)?.code : 'All') },
          { key: 'note', label: 'Note' }, { key: 'created_by', label: 'By' }, { label: 'When', render: (v) => fmtDateTime(v.created_at) }]} empty="Only the built-in sample rules" />
      </Card>
      <Modal open={text !== null} wide title="New statutory rule version" onClose={() => setText(null)} footer={<Button variant="primary" busy={busy} onClick={save}>Save version</Button>}>
        <div className="grid g3">
          <Field label="Effective from"><input className="input" type="date" value={meta.effective_from} onChange={(e) => setMeta({ ...meta, effective_from: e.target.value })} /></Field>
          <Field label="Entity"><Select value={meta.entity_id} onChange={(v) => setMeta({ ...meta, entity_id: v })} options={setup.entities.map((e) => ({ value: e.id, label: e.code }))} placeholder="All entities" /></Field>
          <Field label="Note"><input className="input" value={meta.note} onChange={(e) => setMeta({ ...meta, note: e.target.value })} placeholder="e.g. Budget 2027 slabs" /></Field>
        </div>
        <Field label="Rules (JSON)" error={err}><textarea className="input mono" rows={18} value={text || ''} onChange={(e) => setText(e.target.value)} /></Field>
      </Modal>
    </>
  );
}
