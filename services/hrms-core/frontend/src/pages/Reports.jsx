import { useState } from 'react';
import { api, thisPeriod, useData } from '../lib.jsx';
import { Button, Card, Loading, PageHeader, Table } from '../ui.jsx';

export default function Reports() {
  const { data: list } = useData('/reports');
  const [key, setKey] = useState('headcount');
  const [period, setPeriod] = useState(thisPeriod(0));
  const { data, loading, error } = useData(`/reports/${key}?period=${period}`);
  return (
    <div className="stack">
      <PageHeader title="Reports" sub="Ready-made reports, limited to the staff your role can see. Download any as CSV." />
      <div className="grid g-side">
        <Card pad={false}>
          <nav className="list-nav">{Object.entries(list || {}).map(([k, v]) => <button key={k} className={k === key ? 'on' : ''} onClick={() => setKey(k)}>{v}</button>)}</nav>
        </Card>
        <Card title={data?.title || ''} actions={<>
          <input className="input input-s" type="month" value={period} onChange={(e) => setPeriod(e.target.value)} />
          <Button size="s" onClick={() => api.download(`/reports/${key}?period=${period}&fmt=csv`)}>Download CSV</Button></>} pad={false}>
          {loading ? <Loading /> : error ? <p className="red card-b">{error}</p> : (
            <Table rows={data?.rows} rowKey={(r, i) => i} cols={(data?.columns || []).map((c, i) => ({ key: String(i), label: c, render: (r) => r[i] ?? '—', align: typeof data.rows[0]?.[i] === 'number' ? 'right' : undefined }))} />
          )}
        </Card>
      </div>
    </div>
  );
}
