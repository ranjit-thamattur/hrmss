import { useState } from 'react';
import { api, fmtDate, money, today, useAction, useData } from '../lib.jsx';
import { Badge, Button, Callout, Card, Field, Modal, PageHeader, Table } from '../ui.jsx';

export default function Statutory() {
  const { data: cal, reload } = useData('/statutory/calendar');
  const { data: app } = useData('/statutory/applicability');
  const [item, setItem] = useState(null);
  const [run, busy] = useAction();
  return (
    <div className="stack">
      <PageHeader title="Statutory" sub="Due dates come from locked payroll runs. Enter the challan number once paid." />
      <Callout>Rates and slabs are versioned in Company setup → Statutory rules. The sample rules loaded at setup must be checked by your auditor before going live.</Callout>
      <Card title="Compliance calendar" pad={false}>
        <Table rows={cal} rowKey={(i) => i.key} cols={[{ key: 'law', label: 'Law' }, { key: 'entity', label: 'Entity' }, { key: 'period', label: 'Period' },
          { label: 'Due', render: (i) => fmtDate(i.due) }, { label: 'Amount', align: 'right', render: (i) => money(i.amount) }, { label: 'Status', render: (i) => <Badge value={i.status} /> },
          { label: 'Challan', render: (i) => (i.challan ? `${i.challan.challan_no} · ${fmtDate(i.challan.paid_on)}` : <Button size="s" onClick={() => setItem({ ...i, challan_no: '', paid_on: today(), paid: i.amount })}>Enter challan</Button>) }]}
          empty="Nothing due: lock a payroll run to create the calendar" />
      </Card>
      <Card title="Registrations by entity" pad={false}>
        <Table rows={app} rowKey={(e) => e.entity} cols={[{ key: 'entity', label: 'Entity' }, { key: 'name', label: 'Name' }, { key: 'state', label: 'State' },
          { key: 'pf_code', label: 'EPF code' }, { key: 'esi_code', label: 'ESI code' },
          { label: 'Applies', render: (e) => Object.entries(e.statutory || {}).filter(([, v]) => v).map(([k]) => k.toUpperCase()).join(', ') }]} />
      </Card>
      <Modal open={!!item} title={`Challan · ${item?.law} ${item?.entity} ${item?.period}`} onClose={() => setItem(null)} footer={<Button variant="primary" busy={busy} onClick={async () => {
        if (await run(() => api.post('/statutory/challans', { item_key: item.key, challan_no: item.challan_no, paid_on: item.paid_on, amount: item.paid || null }), 'Challan saved')) { setItem(null); reload(); }
      }}>Save</Button>}>
        <Field label="Challan / reference number"><input className="input" value={item?.challan_no || ''} onChange={(e) => setItem({ ...item, challan_no: e.target.value })} /></Field>
        <Field label="Paid on"><input className="input" type="date" value={item?.paid_on || ''} onChange={(e) => setItem({ ...item, paid_on: e.target.value })} /></Field>
        <Field label="Amount paid (₹)"><input className="input" type="number" value={item?.paid || ''} onChange={(e) => setItem({ ...item, paid: e.target.value })} /></Field>
      </Modal>
    </div>
  );
}
