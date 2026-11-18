import { useState } from 'react';
import { api, fmtDateTime, label, thisPeriod, useAction, useData } from '../lib.jsx';
import { Badge, Button, Callout, Card, Field, PageHeader, Table, Tabs } from '../ui.jsx';

const KINDS = [
  { id: 'employees', label: 'Employees', help: 'One row per employee. Rows with errors are rejected and listed with the reason; the rest are added.' },
  { id: 'salary', label: 'Salary structures', help: 'Employee code, effective-from date and the components (BASIC, HRA, CONV, SPECIAL...). The current version ends the day before.' },
  { id: 'punches', label: 'Biometric punches', help: 'Excel export from the device: either one row per punch (code, date-time) or one row per day (code, date, in, out). Night shifts can end the next morning.' },
  { id: 'inputs', label: 'Monthly pay inputs', help: 'Service charge, incentive, arrears, advance, loan EMI and other one-off amounts for a pay period.' },
];

export default function Imports() {
  const [kind, setKind] = useState('employees');
  const [file, setFile] = useState(null);
  const [period, setPeriod] = useState(thisPeriod(-1));
  const [report, setReport] = useState(null);
  const [run, busy] = useAction();
  const { data: history, reload } = useData('/imports');
  const k = KINDS.find((x) => x.id === kind);

  const send = async (dryRun) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('dry_run', dryRun ? 'true' : 'false');
    if (kind === 'inputs') fd.append('period', period);
    const r = await run(() => api.upload(`/imports/${kind}`, fd), dryRun ? 'File checked' : 'Import done');
    if (r) { setReport(r); reload(); }
  };

  return (
    <div className="stack">
      <PageHeader title="Import from Excel" sub="Check a file first: nothing is saved until you import. Imported + rejected always equals the rows in the file." />
      <Tabs tabs={KINDS} value={kind} onChange={(v) => { setKind(v); setReport(null); setFile(null); }} />
      <Card title={k.label} actions={<Button size="s" onClick={() => api.download(`/imports/templates/${kind}.xlsx`)}>Download template</Button>}>
        <p className="muted">{k.help}</p>
        <div className="row gap wrap mt">
          <Field label="File (.xlsx or .csv)"><input type="file" accept=".xlsx,.csv" onChange={(e) => { setFile(e.target.files?.[0] || null); setReport(null); }} /></Field>
          {kind === 'inputs' && <Field label="Pay period"><input className="input" type="month" value={period} onChange={(e) => setPeriod(e.target.value)} /></Field>}
        </div>
        <div className="row gap-s mt">
          <Button disabled={!file} busy={busy} onClick={() => send(true)}>Check file</Button>
          <Button variant="primary" disabled={!file} busy={busy} onClick={() => send(false)}>Import valid rows</Button>
        </div>
      </Card>
      {report && <Report r={report} />}
      <Card title="Import history" pad={false}>
        <Table rows={history} cols={[{ label: 'When', render: (b) => fmtDateTime(b.created_at) }, { label: 'Kind', render: (b) => label(b.kind) }, { key: 'filename', label: 'File' },
          { key: 'uploaded_by', label: 'By' }, { key: 'total', label: 'Rows', align: 'right' }, { key: 'imported', label: 'OK', align: 'right' }, { key: 'rejected', label: 'Rejected', align: 'right' },
          { label: '', render: (b) => <span className="row gap-s">{b.dry_run && <Badge>Check only</Badge>}
            {b.rejected > 0 && <Button size="s" onClick={() => api.download(`/imports/${b.id}/rejected.csv`)}>Rejected rows</Button>}</span> }]} empty="No imports yet" />
      </Card>
    </div>
  );
}

function Report({ r }) {
  return (
    <Card title={r.dry_run ? 'Check result (nothing saved)' : 'Import result'} actions={r.rejected > 0 && <Button size="s" onClick={() => api.download(`/imports/${r.batch_id}/rejected.csv`)}>Download rejected rows</Button>}>
      <div className="grid g4">
        <div className="stat"><div className="stat-l">Rows in file</div><div className="stat-v">{r.total}</div></div>
        <div className="stat stat-green"><div className="stat-l">{r.dry_run ? 'Would import' : 'Imported'}</div><div className="stat-v">{r.imported}</div></div>
        <div className={`stat ${r.rejected ? 'stat-red' : ''}`}><div className="stat-l">Rejected</div><div className="stat-v">{r.rejected}</div></div>
        <div className="stat"><div className="stat-l">Counts reconcile</div><div className="stat-v">{r.counts_reconcile ? 'Yes' : 'No'}</div></div>
      </div>
      {r.missing_columns?.length > 0 && <Callout tone="red">Missing columns: {r.missing_columns.join(', ')}</Callout>}
      {r.unmapped_columns?.length > 0 && <Callout>Columns ignored: {r.unmapped_columns.join(', ')}</Callout>}
      {r.rejected_rows?.length > 0 && (
        <Table rows={r.rejected_rows.slice(0, 200)} rowKey={(x, i) => i} cols={[{ key: 'row', label: 'Row', width: 60 }, { label: 'Code', render: (x) => x.code || x.data?.code || '—' },
          { label: 'Reason', render: (x) => (Array.isArray(x.errors) ? x.errors.join('; ') : x.reason || x.error) }]} />
      )}
    </Card>
  );
}
