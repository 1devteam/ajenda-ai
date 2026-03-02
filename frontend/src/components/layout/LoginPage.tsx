import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../services/store';
import { auth } from '../../services/api';
import { Btn, Input } from './UI';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { setAuth } = useAuthStore();
  const navigate = useNavigate();

  const handleLogin = async () => {
    if (!username.trim() || !password.trim()) {
      setError('Username and password are required.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const data = await auth.login(username, password);
      setAuth(data.access_token, username);
      navigate('/overview');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Login failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg)',
    }}>
      <div style={{
        width: 380, background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)', padding: 36,
      }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 32 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 8,
            background: 'linear-gradient(135deg, var(--accent), #9B8FFF)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 16, fontWeight: 700, color: '#fff',
          }}>O</div>
          <span style={{ fontSize: 18, fontWeight: 700, letterSpacing: '-0.02em' }}>
            Omni<span style={{ color: 'var(--accent)' }}>Path</span>
            <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-3)', marginLeft: 6 }}>v2</span>
          </span>
        </div>

        <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>Welcome back</div>
        <div style={{ fontSize: 13, color: 'var(--text-2)', marginBottom: 28 }}>
          Sign in to your command center
        </div>

        <Input label="Username" value={username} onChange={setUsername} placeholder="obex" />
        <Input label="Password" value={password} onChange={setPassword} placeholder="••••••••" type="password" />

        {error && (
          <div style={{ color: 'var(--danger)', fontSize: 12, marginBottom: 12, marginTop: -8 }}>{error}</div>
        )}

        <Btn
          variant="primary"
          type="submit"
          onClick={handleLogin}
          disabled={loading}
          style={{ width: '100%', justifyContent: 'center', padding: '10px 14px', fontSize: 14 }}
        >
          {loading ? 'Signing in…' : 'Sign In'}
        </Btn>

        <div style={{ marginTop: 20, padding: 14, background: 'var(--surface-2)', borderRadius: 8, fontSize: 12, color: 'var(--text-2)' }}>
          <strong style={{ color: 'var(--text-1)' }}>PRIDE Protocol Active</strong><br />
          All agent operations are governed by the immutable PRIDE Protocol.
          Machine pride is the measurable equivalence of all proper actions taken across a full process.
        </div>
      </div>
    </div>
  );
}
