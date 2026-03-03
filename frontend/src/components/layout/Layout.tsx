import React from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../services/store';

interface NavItem {
  label: string;
  path: string;
  icon: React.ReactNode;
  badge?: { count: number; variant: 'warning' | 'danger' };
}

const Icon = ({ d, size = 16 }: { d: string; size?: number }) => (
  <svg width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
    <path d={d} />
  </svg>
);

const navGroups: { label: string; items: NavItem[] }[] = [
  {
    label: '',
    items: [
      {
        label: 'Overview',
        path: '/overview',
        icon: (
          <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" />
            <rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" />
          </svg>
        ),
      },
    ],
  },
  {
    label: 'Operations',
    items: [
      {
        label: 'Agents',
        path: '/agents',
        icon: (
          <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <circle cx="12" cy="8" r="4" /><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
          </svg>
        ),
      },
      {
        label: 'Missions',
        path: '/missions',
        icon: (
          <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
          </svg>
        ),
      },
      {
        label: 'Revenue',
        path: '/revenue',
        icon: (
          <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <line x1="12" y1="1" x2="12" y2="23" />
            <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
          </svg>
        ),
      },
    ],
  },
  {
    label: 'Control',
    items: [
      {
        label: 'Governance',
        path: '/governance',
        icon: <Icon d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />,
      },
      {
        label: 'Economy',
        path: '/economy',
        icon: (
          <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <line x1="12" y1="1" x2="12" y2="23" />
            <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
          </svg>
        ),
      },
      {
        label: 'Observability',
        path: '/observability',
        icon: (
          <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
          </svg>
        ),
      },
    ],
  },
  {
    label: 'Workspace',
    items: [
      {
        label: 'Intelligence',
        path: '/intelligence',
        icon: <Icon d="M12 2a10 10 0 1 0 0 20A10 10 0 0 0 12 2z M12 8v4l3 3" />,
      },
      {
        label: 'Settings',
        path: '/settings',
        icon: (
          <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        ),
      },
    ],
  },
];

interface LayoutProps {
  children: React.ReactNode;
  title?: string;
  subtitle?: string;
  actions?: React.ReactNode;
}

export default function Layout({ children, title, subtitle, actions }: LayoutProps) {
  const { username, logout } = useAuthStore();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', background: 'var(--bg)' }}>
      {/* Sidebar */}
      <aside style={{
        width: 'var(--sidebar-w)',
        minWidth: 'var(--sidebar-w)',
        background: 'var(--surface)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}>
        {/* Logo */}
        <div style={{
          height: 'var(--header-h)',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '0 16px',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
        }}>
          <div style={{
            width: 28, height: 28, borderRadius: 6,
            background: 'linear-gradient(135deg, var(--accent), #9B8FFF)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 13, fontWeight: 700, color: '#fff', flexShrink: 0,
          }}>O</div>
          <span style={{ fontSize: 15, fontWeight: 700, letterSpacing: '-0.02em' }}>
            Omni<span style={{ color: 'var(--accent)' }}>Path</span>
          </span>
        </div>

        {/* Nav */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
          {navGroups.map((group) => (
            <div key={group.label} style={{ padding: '0 8px', marginBottom: 4 }}>
              {group.label && (
                <div style={{
                  fontSize: 10, fontWeight: 600, letterSpacing: '0.1em',
                  textTransform: 'uppercase', color: 'var(--text-3)',
                  padding: '8px 8px 4px',
                }}>
                  {group.label}
                </div>
              )}
              {group.items.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  style={({ isActive }) => ({
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    padding: '8px 10px',
                    borderRadius: 'var(--radius)',
                    color: isActive ? 'var(--accent)' : 'var(--text-2)',
                    background: isActive ? 'var(--accent-dim)' : 'transparent',
                    fontSize: 13,
                    fontWeight: 500,
                    cursor: 'pointer',
                    marginBottom: 2,
                    textDecoration: 'none',
                    transition: 'all 0.15s',
                  })}
                >
                  {item.icon}
                  <span style={{ flex: 1 }}>{item.label}</span>
                  {item.badge && (
                    <span style={{
                      background: item.badge.variant === 'danger' ? 'var(--danger)' : 'var(--warning)',
                      color: item.badge.variant === 'danger' ? '#fff' : '#000',
                      fontSize: 10, fontWeight: 700,
                      padding: '1px 6px', borderRadius: 10,
                    }}>
                      {item.badge.count}
                    </span>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </div>

        {/* User footer */}
        <div style={{ padding: '12px 8px', borderTop: '1px solid var(--border)', flexShrink: 0 }}>
          <div
            onClick={handleLogout}
            style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '8px 10px', borderRadius: 'var(--radius)',
              cursor: 'pointer',
            }}
            title="Click to logout"
          >
            <div style={{
              width: 28, height: 28, borderRadius: '50%',
              background: 'linear-gradient(135deg, var(--accent), #9B8FFF)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 11, fontWeight: 700, color: '#fff', flexShrink: 0,
            }}>
              {(username || 'OB').slice(0, 2).toUpperCase()}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{username || 'Obex Blackvault'}</div>
              <div style={{ fontSize: 11, color: 'var(--text-2)' }}>Owner · Admin</div>
            </div>
          </div>
        </div>
      </aside>

      {/* Main area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Topbar */}
        {(title || actions) && (
          <div style={{
            height: 'var(--header-h)',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            padding: '0 24px',
            gap: 16,
            flexShrink: 0,
          }}>
            <div>
              {title && <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-1)' }}>{title}</span>}
            </div>
            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '4px 10px',
                background: 'var(--surface-2)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius)',
                fontSize: 12, color: 'var(--text-2)',
              }}>
                <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--success)' }} />
                production
              </div>
              {actions}
            </div>
          </div>
        )}

        {/* Page content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
          {(title || subtitle) && (
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24 }}>
              <div>
                {title && <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: '-0.02em' }}>{title}</div>}
                {subtitle && <div style={{ fontSize: 13, color: 'var(--text-2)', marginTop: 2 }}>{subtitle}</div>}
              </div>
            </div>
          )}
          {children}
        </div>
      </div>
    </div>
  );
}
