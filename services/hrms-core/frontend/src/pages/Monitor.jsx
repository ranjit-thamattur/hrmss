import { useEffect, useState } from 'react';
import { api, fmtDateTime, label, useAction, useData } from '../lib.jsx';
import { Badge, Button, Callout, Card, ErrorBox, Loading, PageHeader, Table, Tabs } from '../ui.jsx';

// Monitoring dashboard for the 5 core services (SCRUM-130). Master admin only.
const STATUS_TEXT = { up: 'Up', degraded: 'Degraded', down: 'Down', unknown: 'Not checked' };
const DOT = { up: 'var(--green)', degraded: 'var(--amber)', down: 'var(--red)', unknown: 'var(--muted)' };
const METRIC_LABELS = {
  requests_15m: 'Requests (15 min)', errors_15m: 'Server errors (15 min)', p95_ms: '95% of requests under (ms)', uptime_s: 'Running for', version: 'Version',
  engine: 'Engine', size_mb: 'Size (MB)', connections: 'Connections', employees: 'Employees',
  mode: 'Mode', active_users: 'Active users', failed_tasks: 'Failed sign-in tasks',
  adapter: 'Adapter', last_punch: 'Newest punch', hours_since_last_punch: 'Hours since newest punch', enrolments_open: 'Enrolments to do',
};

function fmtMetric(k, v) {
  if (v === null || v === undefined) return '—';
  if (k === 'uptime_s') { const h = Math.floor(v / 3600); return h >= 24 ? `${Math.floor(h / 24)} d ${h % 24} h` : `${h} h ${Math.floor((v % 3600) / 60)} m`; }
  if (k === 'last_punch') return fmtDateTime(v);
  if (k === 'error_rate') return `${(v * 100).toFixed(1)}%`;
  return String(v);
}

function Spark({ points }) {
  const w = 240; const h = 44;
  if (!points?.length) return <div className="spark muted small">No history yet</div>;
  const vals = points.map((p) => p.latency_ms ?? 0);
  const max = Math.max(...vals, 1);
  const step = points.length > 1 ? w / (points.length - 1) : 0;
  const y = (v) => h - 4 - ((v ?? 0) / max) * (h - 10);
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${(i * step).toFixed(1)},${y(p.latency_ms).toFixed(1)}`).join(' ');
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label="Response time, recent checks">
      <path d={line} fill="none" stroke="var(--line-strong, #94a3b8)" strokeWidth="1.5" />
      {points.map((p, i) => (p.status !== 'up' ? <circle key={i} cx={i * step} cy={y(p.latency_ms)} r="3" fill={DOT[p.status]} /> : null))}
    </svg>
  );
}

function ServiceCard({ s }) {
  const metrics = Object.entries(s.metrics || {}).filter(([k]) => METRIC_LABELS[k]);
  return (
    <section className={`card mon-card mon-${s.status}`}>
      <header className="card-h"><h3>{s.label}</h3><Badge value={s.status}>{STATUS_TEXT[s.status] || label(s.status)}</Badge></header>
      <div className="card-b stack-s">
        <p className="mon-detail">{s.detail}</p>
        <div className="mon-nums">
          <div><span className="muted small">Response</span><b>{s.latency_ms !== null && s.latency_ms !== undefined ? `${s.latency_ms} ms` : '—'}</b></div>
          <div><span className="muted small">Up, last 24 h</span><b>{s.uptime_24h !== null && s.uptime_24h !== undefined ? `${s.uptime_24h}%` : '—'}</b></div>
        </div>
        <Spark points={s.recent} />
        {metrics.length > 0 && <dl className="kv small">{metrics.map(([k, v]) => [<dt key={`${k}l`}>{METRIC_LABELS[k]}</dt>, <dd key={k}>{fmtMetric(k, v)}</dd>])}</dl>}
        <p className="muted small">Checked {fmtDateTime(s.at)}</p>
      </div>
    </section>
  );
}

export default function Monitor() {
  const { data, error, loading, reload, setData } = useData('/monitor/status');
  const [tab, setTab] = useState('open');
  const { data: alerts, reload: reloadAlerts } = useData(`/monitor/alerts?state=${tab}`);
  const [run, busy] = useAction();

  useEffect(() => {
    const t = setInterval(() => { reload(); reloadAlerts(); }, 30000);
    return () => clearInterval(t);
  }, [reload, reloadAlerts]);

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const down = data.services.filter((s) => s.status === 'down');
  const degraded = data.services.filter((s) => s.status === 'degraded');
  const checkNow = async () => { const r = await run(() => api.get('/monitor/status?refresh=true'), 'Checked all services'); if (r) { setData(r); reloadAlerts(); } };
  const ack = async (a) => { if (await run(() => api.post(`/monitor/alerts/${a.id}/ack`), 'Alert acknowledged')) { reloadAlerts(); reload(); } };

  return (
    <div className="stack">
      <PageHeader title="Monitoring" sub={`Health of the 5 core services, checked every ${data.interval_seconds || 60} seconds. Last check ${fmtDateTime(data.checked_at)}.`}
        actions={<Button busy={busy} onClick={checkNow}>Check now</Button>} />
      {down.length > 0 && <Callout tone="red"><b>Down:</b> {down.map((s) => s.label).join(', ')}.</Callout>}
      {!down.length && degraded.length > 0 && <Callout tone="amber"><b>Needs attention:</b> {degraded.map((s) => s.label).join(', ')}.</Callout>}
      {!down.length && !degraded.length && <Callout tone="green">All checked services are up.</Callout>}
      <div className="mon-grid">{data.services.map((s) => <ServiceCard key={s.service} s={s} />)}</div>
      <Card title="Alerts" actions={<Tabs tabs={[{ id: 'open', label: 'Open', count: data.open_alerts.length }, { id: 'all', label: 'History' }]} value={tab} onChange={setTab} />} pad={false}>
        <Table rows={alerts} rowClass={(a) => (a.resolved_at ? '' : `row-${a.severity}`)} cols={[
          { label: 'Severity', render: (a) => <Badge value={a.severity}>{label(a.severity)}</Badge> },
          { label: 'Service', render: (a) => data.services.find((s) => s.service === a.service)?.label || a.service },
          { key: 'message', label: 'What happened' },
          { label: 'Opened', render: (a) => fmtDateTime(a.opened_at) },
          { label: 'Resolved', render: (a) => (a.resolved_at ? fmtDateTime(a.resolved_at) : <Badge tone="red">Open</Badge>) },
          { label: 'Acknowledged', render: (a) => (a.acknowledged_by ? <span className="small">{a.acknowledged_by}<br />{fmtDateTime(a.acknowledged_at)}</span>
            : <Button size="s" busy={busy} onClick={() => ack(a)}>Acknowledge</Button>) },
        ]} empty={tab === 'open' ? 'No open alerts' : 'No alerts yet'} />
      </Card>
      <p className="muted small">Rules: down on 2 checks in a row raises a critical alert; degraded on 3 checks in a row raises a warning; an alert closes by itself when the service is up again. If MONITOR_ALERT_EMAILS is set, new alerts are also queued as emails in the outbox.</p>
    </div>
  );
}
