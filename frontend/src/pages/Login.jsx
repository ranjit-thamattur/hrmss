import { useState } from 'react';
import { api, navigate, useApp } from '../lib.jsx';
import { Button, Callout, Field } from '../ui.jsx';

export default function Login() {
  const { loadMe } = useApp();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [challenge, setChallenge] = useState(null);
  const [newPw, setNewPw] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const finish = async (token) => {
    api.setToken(token);
    await loadMe();
    navigate('/');
  };

  const submit = async (e) => {
    e.preventDefault();
    setError(''); setBusy(true);
    try {
      if (challenge) {
        const r = await api.post('/auth/new-password', { email, new_password: newPw, session: challenge });
        await finish(r.token);
      } else {
        const r = await api.post('/auth/login', { email, password });
        if (r.challenge === 'NEW_PASSWORD_REQUIRED') setChallenge(r.session);
        else await finish(r.token);
      }
    } catch (err) { setError(err.message); }
    setBusy(false);
  };

  return (
    <div className="login">
      <div className="login-l">
        <div className="row gap-s"><span className="logo" style={{ background: '#fff', color: 'var(--accent)' }}>HR</span><b>Peak HRMS</b></div>
        <div>
          <h1>Hotel Vivek HR: people, attendance and payroll for 3 entities and 5 locations.</h1>
          <p style={{ opacity: 0.85, marginTop: 12, maxWidth: 420 }}>Employee records, biometric attendance, payroll with HR and Finance approval, statutory files, exits and self-service.</p>
        </div>
        <div className="small" style={{ opacity: 0.7 }}>Sign-in is managed by your administrator.</div>
      </div>
      <div className="login-r">
        <form className="login-box" onSubmit={submit}>
          <h2>{challenge ? 'Set your password' : 'Sign in'}</h2>
          {challenge && <Callout tone="blue">First sign-in: choose your own password (8+ characters with an upper-case letter, a lower-case letter and a number).</Callout>}
          <Field label="Email"><input className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required disabled={!!challenge} /></Field>
          {!challenge
            ? <Field label="Password"><input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></Field>
            : <Field label="New password"><input className="input" type="password" autoComplete="new-password" value={newPw} onChange={(e) => setNewPw(e.target.value)} required /></Field>}
          {error && <Callout tone="red">{error}</Callout>}
          <Button variant="primary" type="submit" busy={busy}>{challenge ? 'Save and sign in' : 'Sign in'}</Button>
          <p className="muted small">Demo users (seeded): admin@, hr@, payroll@, finance@, hod@, employee@hotelvivek.local · password from DEMO_PASSWORD (default Peak@12345)</p>
        </form>
      </div>
    </div>
  );
}
