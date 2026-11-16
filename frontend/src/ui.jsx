import { useEffect, useState } from 'react';
import { label } from './lib.jsx';

export function Button({ variant = 'secondary', size, busy, children, className = '', ...rest }) {
  return (
    <button className={`btn btn-${variant} ${size === 's' ? 'btn-s' : ''} ${className}`} disabled={busy || rest.disabled} {...rest}>
      {busy ? <span className="spinner" aria-hidden /> : null}{children}
    </button>
  );
}

const TONES = {
  active: 'green', done: 'green', approved: 'green', locked: 'green', paid: 'green', present: 'green', closed: 'grey', applied: 'green', fnf_approved: 'green',
  pending: 'amber', pending_hod: 'amber', pending_hr: 'amber', calculated: 'blue', reviewed: 'blue', hr_approved: 'blue', finance_approved: 'blue',
  notice: 'amber', manual: 'amber', due: 'blue', fnf_calculated: 'blue', missed_punch: 'red', absent: 'red', failed: 'red', overdue: 'red', rejected: 'red',
  exited: 'grey', leave: 'violet', weekly_off: 'grey', holiday: 'violet', block: 'red', warn: 'amber', open: 'blue', proposed: 'grey', hold: 'red', accept: 'green',
};
export function Badge({ children, tone, value }) {
  const t = tone || TONES[value] || 'grey';
  return <span className={`badge badge-${t}`}>{children ?? label(value)}</span>;
}

export function Card({ title, actions, children, className = '', pad = true }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && <header className="card-h"><h3>{title}</h3>{actions && <div className="row gap-s wrap">{actions}</div>}</header>}
      <div className={pad ? 'card-b' : ''}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, sub, actions }) {
  return (
    <div className="page-h">
      <div><h1>{title}</h1>{sub && <p className="muted">{sub}</p>}</div>
      {actions && <div className="row gap-s wrap">{actions}</div>}
    </div>
  );
}

export function Stat({ label: l, value, sub, tone, onClick }) {
  const El = onClick ? 'button' : 'div';
  return (
    <El className={`stat ${onClick ? 'clickable' : ''} ${tone ? `stat-${tone}` : ''}`} onClick={onClick}>
      <div className="stat-l">{l}</div><div className="stat-v">{value}</div>{sub && <div className="stat-s">{sub}</div>}
    </El>
  );
}

export function Table({ cols, rows, empty = 'Nothing to show', onRow, rowKey = (r, i) => r.id ?? i, rowClass }) {
  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <thead><tr>{cols.map((c) => <th key={c.key || c.label} style={{ textAlign: c.align, width: c.width }}>{c.label}</th>)}</tr></thead>
        <tbody>
          {(!rows || rows.length === 0) && <tr><td colSpan={cols.length} className="empty">{empty}</td></tr>}
          {rows?.map((r, i) => (
            <tr key={rowKey(r, i)} className={`${onRow ? 'clickable' : ''} ${rowClass ? rowClass(r) : ''}`} onClick={onRow ? () => onRow(r) : undefined}>
              {cols.map((c) => <td key={c.key || c.label} style={{ textAlign: c.align }}>{c.render ? c.render(r) : r[c.key] ?? '—'}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => {
        const id = t.id ?? t;
        return <button key={id} role="tab" aria-selected={value === id} className={value === id ? 'on' : ''} onClick={() => onChange(id)}>{t.label ?? t}{t.count ? <span className="tab-c">{t.count}</span> : null}</button>;
      })}
    </div>
  );
}

export function Field({ label: l, hint, children, error, group }) {
  // group: the field holds several controls (chips, radios), so it must not be a <label>
  const El = group ? 'div' : 'label';
  return (
    <El className="field">
      <span className="field-l">{l}</span>
      {children}
      {error ? <span className="field-e">{error}</span> : hint ? <span className="field-h">{hint}</span> : null}
    </El>
  );
}

export function Select({ value, onChange, options, placeholder, ...rest }) {
  return (
    <select className="input" value={value ?? ''} onChange={(e) => onChange(e.target.value)} {...rest}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((o) => <option key={o.value ?? o} value={o.value ?? o}>{o.label ?? o}</option>)}
    </select>
  );
}

export function Modal({ open, title, onClose, children, footer, wide }) {
  useEffect(() => {
    if (!open) return undefined;
    const k = (e) => e.key === 'Escape' && onClose?.();
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <header className="modal-h"><h3>{title}</h3><button className="icon-btn" onClick={onClose} aria-label="Close">×</button></header>
        <div className="modal-b">{children}</div>
        {footer && <footer className="modal-f">{footer}</footer>}
      </div>
    </div>
  );
}

export function Callout({ tone = 'grey', children }) {
  return <div className={`callout callout-${tone}`}>{children}</div>;
}

export function Loading({ what = 'Loading' }) {
  return <div className="loading"><span className="spinner" /> {what}…</div>;
}

export function ErrorBox({ error }) {
  return error ? <Callout tone="red">{error}</Callout> : null;
}

export function Pager({ page, size, total, onPage }) {
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <div className="pager">
      <span className="muted">{total ? `${(page - 1) * size + 1}–${Math.min(total, page * size)} of ${total}` : '0'}</span>
      <span className="row gap-s"><Button size="s" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
        <span>{page} / {pages}</span><Button size="s" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button></span>
    </div>
  );
}

export function useForm(initial) {
  const [v, setV] = useState(initial);
  const bind = (k, type) => ({
    value: v[k] ?? '',
    onChange: (e) => setV((s) => ({ ...s, [k]: type === 'checkbox' ? e.target.checked : e.target.value })),
    ...(type === 'checkbox' ? { checked: !!v[k] } : {}),
  });
  return [v, setV, bind];
}

export function Confirm({ open, title, text, onYes, onNo, yes = 'Confirm', busy }) {
  return (
    <Modal open={open} title={title} onClose={onNo} footer={<><Button variant="ghost" onClick={onNo}>Cancel</Button><Button variant="primary" busy={busy} onClick={onYes}>{yes}</Button></>}>
      <p>{text}</p>
    </Modal>
  );
}
