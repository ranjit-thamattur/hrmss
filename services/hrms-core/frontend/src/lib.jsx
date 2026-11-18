import { createContext, useCallback, useContext, useEffect, useState } from 'react';

// ---------------------------------------------------------------- session + API
const TOKEN_KEY = 'peak-hrms-token';
const store = {
  get: () => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set: (t) => { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* storage blocked */ } },
};

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function request(method, path, body, { raw = false, form = false } = {}) {
  const headers = {};
  const token = store.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload;
  if (form) payload = body;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  const res = await fetch(`/api${path}`, { method, headers, body: payload });
  if (res.status === 401 && path !== '/auth/login') {
    store.set(null);
    window.dispatchEvent(new Event('hrms-signed-out'));
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === 'string' ? j.detail : Array.isArray(j.detail) ? j.detail.map((d) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join('; ') : msg;
    } catch { /* not json */ }
    throw new ApiError(res.status, msg);
  }
  if (raw) return res;
  const ct = res.headers.get('content-type') || '';
  return ct.includes('json') ? res.json() : res.text();
}

export const api = {
  get: (p) => request('GET', p),
  post: (p, b) => request('POST', p, b),
  put: (p, b) => request('PUT', p, b),
  patch: (p, b) => request('PATCH', p, b),
  del: (p) => request('DELETE', p),
  upload: (p, formData) => request('POST', p, formData, { form: true }),
  async download(p, fallbackName) {
    const res = await request('GET', p, undefined, { raw: true });
    const blob = await res.blob();
    const cd = res.headers.get('content-disposition') || '';
    const name = (cd.match(/filename="([^"]+)"/) || [])[1] || fallbackName || 'download';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  },
  setToken: store.set,
  hasToken: () => !!store.get(),
};

export const qs = (o) => {
  const p = Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== '');
  return p.length ? '?' + p.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&') : '';
};

// ---------------------------------------------------------------- app context (user, setup data, toasts)
const AppCtx = createContext(null);
export const useApp = () => useContext(AppCtx);

export function AppProvider({ children }) {
  const [me, setMe] = useState(null);
  const [setup, setSetup] = useState(null);
  const [toast, setToast] = useState(null);
  const [loading, setLoading] = useState(api.hasToken());

  const notify = useCallback((text, tone = 'ok') => {
    setToast({ text, tone, id: Date.now() });
  }, []);

  const loadMe = useCallback(async () => {
    if (!api.hasToken()) { setMe(null); setLoading(false); return; }
    try {
      const [m, s] = await Promise.all([api.get('/auth/me'), api.get('/org/all')]);
      setMe(m); setSetup(s);
    } catch { setMe(null); }
    setLoading(false);
  }, []);

  const reloadSetup = useCallback(async () => setSetup(await api.get('/org/all')), []);

  useEffect(() => { loadMe(); }, [loadMe]);
  useEffect(() => {
    const out = () => setMe(null);
    window.addEventListener('hrms-signed-out', out);
    return () => window.removeEventListener('hrms-signed-out', out);
  }, []);
  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(null), toast.tone === 'error' ? 6000 : 3000);
    return () => clearTimeout(t);
  }, [toast]);

  const can = useCallback((perm) => !!me?.permissions?.includes(perm), [me]);
  const signOut = () => { api.setToken(null); setMe(null); navigate('/login'); };

  return (
    <AppCtx.Provider value={{ me, setup, loading, notify, loadMe, reloadSetup, can, signOut }}>
      {children}
      {toast && <div className={`toast toast-${toast.tone}`} role="status">{toast.text}</div>}
    </AppCtx.Provider>
  );
}

// ---------------------------------------------------------------- tiny router (history API)
export function navigate(to) {
  window.history.pushState(null, '', to);
  window.dispatchEvent(new Event('hrms-route'));
  window.scrollTo(0, 0);
}

export function useRoute() {
  const read = () => ({ path: window.location.pathname, search: new URLSearchParams(window.location.search) });
  const [r, setR] = useState(read);
  useEffect(() => {
    const on = () => setR(read());
    window.addEventListener('popstate', on);
    window.addEventListener('hrms-route', on);
    return () => { window.removeEventListener('popstate', on); window.removeEventListener('hrms-route', on); };
  }, []);
  return r;
}

export function Link({ to, children, className = 'link', ...rest }) {
  return <a href={to} className={className} onClick={(e) => { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); navigate(to); }} {...rest}>{children}</a>;
}

// ---------------------------------------------------------------- data hook
export function useData(path, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: !!path });
  const load = useCallback(async () => {
    if (!path) return;
    setState((s) => ({ ...s, loading: true }));
    try { setState({ data: await api.get(path), error: null, loading: false }); }
    catch (e) { setState({ data: null, error: e.message, loading: false }); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => { load(); }, [load]);
  return { ...state, reload: load, setData: (d) => setState((s) => ({ ...s, data: d })) };
}

// Runs an action, shows success or the API's error message.
export function useAction() {
  const { notify } = useApp();
  const [busy, setBusy] = useState(false);
  const run = useCallback(async (fn, success) => {
    setBusy(true);
    try {
      const r = await fn();
      if (success) notify(typeof success === 'function' ? success(r) : success);
      return r;
    } catch (e) {
      notify(e.message || 'Something went wrong', 'error');
      return undefined;
    } finally { setBusy(false); }
  }, [notify]);
  return [run, busy];
}

// ---------------------------------------------------------------- formatting
const inr = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
export const money = (v) => (v === null || v === undefined || v === '' ? '—' : `₹${inr.format(Number(v))}`);
export const num = (v) => (v === null || v === undefined ? '—' : inr.format(Number(v)));
export const fmtDate = (s) => {
  if (!s) return '—';
  const d = new Date(s.length <= 10 ? `${s}T00:00:00` : s);
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
};
export const fmtDateTime = (s) => (s ? new Date(s).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—');
export const fmtTime = (s) => (s ? new Date(s).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : '—');
export const label = (s) => (s || '').replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
export const thisPeriod = (offset = 0) => {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
};
export const today = () => new Date().toISOString().slice(0, 10);
