import { useState } from 'react';
import { api, fmtDateTime, label, useAction, useApp, useData } from '../lib.jsx';
import tenant from '@tenant/tenant.js';
import { Badge, Button, Callout, Card, Field, Modal, PageHeader, Table, Tabs } from '../ui.jsx';

const OTHER_LANGS = tenant.languages.filter((l) => l.code !== 'en');

export default function Comms() {
  const { setup } = useApp();
  const [tab, setTab] = useState('circulars');
  const { data: circs, reload } = useData('/circulars');
  const { data: outbox, reload: reloadOut } = useData(tab === 'outbox' ? '/outbox' : null);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ title: '', en: '', location_ids: [], department_ids: [] });
  const [run, busy] = useAction();
  const toggle = (k, v) => setF({ ...f, [k]: f[k].includes(v) ? f[k].filter((x) => x !== v) : [...f[k], v] });
  return (
    <div className="stack">
      <PageHeader title="Circulars & messages" sub="Messages are queued in the outbox. WhatsApp sending is switched on once the business account is approved." actions={<>
        <Button busy={busy} onClick={async () => { if (await run(() => api.post('/wishes/today'), 'Today\'s wishes queued')) reloadOut(); }}>Queue today's wishes</Button>
        <Button variant="primary" onClick={() => setOpen(true)}>New circular</Button></>} />
      <Tabs tabs={[{ id: 'circulars', label: 'Circulars' }, { id: 'outbox', label: 'Outbox' }]} value={tab} onChange={setTab} />
      {tab === 'circulars' ? (
        <Card pad={false}>
          <Table rows={circs} cols={[{ key: 'title', label: 'Title' }, { label: 'Sent', render: (c) => fmtDateTime(c.sent_at) }, { key: 'sent_by', label: 'By' },
            { key: 'recipients', label: 'Recipients', align: 'right' }, { key: 'reads', label: 'Read', align: 'right' }, { label: 'Languages', render: (c) => Object.keys(c.body).filter((k) => c.body[k]).join(', ') }]} empty="No circulars yet" />
        </Card>
      ) : (
        <Card pad={false}>
          <Table rows={outbox} cols={[{ label: 'When', render: (o) => fmtDateTime(o.created_at) }, { key: 'channel', label: 'Channel' }, { key: 'to', label: 'To' },
            { label: 'Template', render: (o) => label(o.template) }, { label: 'Status', render: (o) => <Badge>{label(o.status)}</Badge> }]} empty="Outbox is empty" />
        </Card>
      )}
      <Modal open={open} wide title="New circular" onClose={() => setOpen(false)} footer={<Button variant="primary" busy={busy} onClick={async () => {
        const body = { title: f.title, body: { en: f.en, ...Object.fromEntries(OTHER_LANGS.filter((l) => f[l.code]).map((l) => [l.code, f[l.code]])) }, location_ids: f.location_ids, department_ids: f.department_ids };
        const r = await run(() => api.post('/circulars', body), 'Circular queued');
        if (r) { setOpen(false); reload(); }
      }}>Send</Button>}>
        <Field label="Title"><input className="input" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
        <Field label="English (required)"><textarea className="input" rows={3} value={f.en} onChange={(e) => setF({ ...f, en: e.target.value })} /></Field>
        <div className="grid g2">
          {OTHER_LANGS.map((l) => <Field key={l.code} label={l.label}><textarea className="input" rows={3} value={f[l.code] || ''} onChange={(e) => setF({ ...f, [l.code]: e.target.value })} /></Field>)}
        </div>
        <Callout>Each employee gets their own language, or English if that text is empty. Have each translation checked by a native speaker.</Callout>
        <Field group label="Locations" hint="None = all"><div className="chips">{setup.locations.map((l) => <button key={l.id} type="button" className={`chip ${f.location_ids.includes(l.id) ? 'on' : ''}`} onClick={() => toggle('location_ids', l.id)}>{l.name}</button>)}</div></Field>
        <Field group label="Departments" hint="None = all"><div className="chips">{setup.departments.map((d) => <button key={d.id} type="button" className={`chip ${f.department_ids.includes(d.id) ? 'on' : ''}`} onClick={() => toggle('department_ids', d.id)}>{d.name}</button>)}</div></Field>
      </Modal>
    </div>
  );
}
