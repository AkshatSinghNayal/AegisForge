import { useEffect, useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Button, Input, Wordmark } from '@/ui';
import { login, request, messageSchema } from './client';
import './product.css';
const titles: Record<string, string> = {
  'sign-in': 'Welcome back.',
  'sign-up': 'Build with confidence.',
  'forgot-password': 'Reset your password.',
  'reset-password': 'Choose a new password.',
  'verify-email': 'Verify your email.',
  'accept-invite': 'Join your organization.',
};
export default function Auth() {
  const location = useLocation();
  const kind = location.pathname.split('/').pop() ?? 'sign-in';
  const navigate = useNavigate();
  const [token] = useState(() => {
    const value =
      new URLSearchParams(window.location.hash.slice(1)).get('token') ?? '';
    return value;
  });
  useEffect(() => {
    document.title = `${titles[kind] ?? 'Account'} | AegisForge`;
    if (token)
      window.history.replaceState(
        window.history.state,
        '',
        window.location.pathname,
      );
  }, [kind, token]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setMessage('');
    const form = new FormData(event.currentTarget);
    const email = String(form.get('email') ?? '');
    const password = String(form.get('password') ?? '');
    try {
      if (kind === 'sign-in') {
        await login(email, password);
        navigate('/app/getting-started');
      } else {
        const body =
          kind === 'sign-up'
            ? {
                email,
                password,
                display_name: form.get('display_name'),
                organization_name: form.get('organization_name'),
              }
            : kind === 'forgot-password'
              ? { email }
              : kind === 'reset-password'
                ? { token, password }
                : { token };
        const path =
          kind === 'sign-up'
            ? '/auth/register'
            : kind === 'accept-invite'
              ? '/organizations/accept-invite'
              : `/auth/${kind}`;
        if (kind === 'accept-invite') {
          await login(email, password);
        }
        setMessage((await request(path, messageSchema, 'POST', body)).message);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Please try again.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="identity-page">
      <section className="identity-story">
        <Link to="/" aria-label="AegisForge home">
          <Wordmark />
        </Link>
        <p className="eyebrow">YOUR SECURITY WORKSPACE</p>
        <h1>
          Ship boldly.
          <br />
          <span>Verify deliberately.</span>
        </h1>
        <p>
          Bring your team, projects, and security evidence into one clear view.
        </p>
        <Link to="/docs/authorization">Built around authorized testing ↗</Link>
      </section>
      <section className="identity-form">
        <p className="eyebrow">AEGISFORGE / ACCOUNT</p>
        <h2>{titles[kind]}</h2>
        <form key={kind} onSubmit={(e) => void submit(e)}>
          {['sign-in', 'sign-up', 'forgot-password', 'accept-invite'].includes(
            kind,
          ) && (
            <Input
              label="Email"
              name="email"
              type="email"
              autoComplete="email"
              required
              maxLength={320}
            />
          )}
          {kind === 'sign-up' && (
            <>
              <Input
                label="Your name"
                name="display_name"
                autoComplete="name"
                required
                maxLength={120}
              />
              <Input
                label="Organization name"
                name="organization_name"
                autoComplete="organization"
                required
                maxLength={120}
              />
            </>
          )}
          {['sign-in', 'sign-up', 'reset-password', 'accept-invite'].includes(
            kind,
          ) && (
            <Input
              label="Password"
              name="password"
              type="password"
              autoComplete={
                ['sign-in', 'accept-invite'].includes(kind)
                  ? 'current-password'
                  : 'new-password'
              }
              minLength={['sign-in', 'accept-invite'].includes(kind) ? 1 : 12}
              maxLength={128}
              required
            />
          )}
          {['sign-up', 'reset-password'].includes(kind) && (
            <p className="muted">Use at least 12 characters.</p>
          )}
          {['reset-password', 'verify-email', 'accept-invite'].includes(kind) &&
            !token && (
              <p role="alert">Open the link from your email to continue.</p>
            )}
          {error && <p role="alert">{error}</p>}
          {message && <p role="status">{message}</p>}
          <Button
            type="submit"
            disabled={
              busy ||
              (['reset-password', 'verify-email', 'accept-invite'].includes(
                kind,
              ) &&
                !token)
            }
          >
            {busy
              ? 'Please wait…'
              : kind === 'sign-in'
                ? 'Sign in'
                : kind === 'sign-up'
                  ? 'Create account'
                  : kind === 'forgot-password'
                    ? 'Send reset link'
                    : 'Continue'}
          </Button>
        </form>
        <div className="identity-links">
          <Link to="/auth/sign-in">Sign in</Link>
          <Link to="/auth/sign-up">Create an account</Link>
          <Link to="/auth/forgot-password">Forgot password?</Link>
        </div>
      </section>
    </main>
  );
}
