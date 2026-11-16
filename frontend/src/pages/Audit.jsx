import { useState } from 'react';
import { fmtDateTime, label, qs, useData } from '../lib.jsx';
import { Card, PageHeader, Select, Table } from '../ui.jsx';

const TYPES = ['employee', 'user', 'payroll_run', 'payroll_line', 'attendance_day', 'leave', 'exit', 'import', 'policy', 'statutory_rules', 'org', 'provisioning'];

export default function Audit() {
  const [f, setF] = useState({ entity_type: '', actor: '', q: '' });
  const { data } = useData(`/audit${qs({ ...f, limit: 500 })}`);
  return (
    <div className="stack">
      <PageHeader title="Audit trail" sub="Every change, who made it and when. Entries can only be added, never edited or deleted (enforced in the database)." />
      <Card pad={false}>
        <div className="filters">
          <Select className="input input-s" value={f.entity_type} onChange={(v) => setF({ ...f, entity_type: v })} options={TYPES.map((t) => ({ value: t, label: label(t) }))} placeholder="All records" />
          <input className="input input-s" placeholder="Who (email)" value={f.actor} onChange={(e) => setF({ ...f, actor: e.target.value })} />
          <input className="input input-s" placeholder="Action or record id" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        </div>
        <Table rows={data} cols={[{ label: 'When', render: (a) => fmtDateTime(a.at) }, { key: 'actor', label: 'Who' }, { label: 'Action', render: (a) => label(a.action) },
          { label: 'Record', render: (a) => `${label(a.entity_type)} ${a.entity_id ?? ''}` },
          { label: 'Change', render: (a) => <div className="mono small audit-diff">{a.before && <div className="red">− {JSON.stringify(a.before).slice(0, 200)}</div>}{a.after && <div className="green">+ {JSON.stringify(a.after).slice(0, 200)}</div>}</div> }]} />
      </Card>
    </div>
  );
}
