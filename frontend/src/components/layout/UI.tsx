/**
 * Shared UI primitives — matches the wireframe design system exactly.
 */
import React from 'react';

// ---- Badge ----
type BadgeVariant = 'active' | 'pending' | 'error' | 'inactive' | 'info';

export function Badge({ variant, children }: { variant: BadgeVariant; children: React.ReactNode }) {
  const styles: Record<BadgeVariant, { bg: string; color: string }> = {
    active:   { bg: 'rgba(34,211,160,0.12)',  color: 'var(--success)' },
    pending:  { bg: 'rgba(245,158,11,0.12)',  color: 'var(--warning)' },
    error:    { bg: 'rgba(239,68,68,0.12)',   color: 'var(--danger)'  },
    inactive: { bg: 'rgba(139,147,168,0.12)', color: 'var(--text-2)'  },
    info:     { bg: 'rgba(108,99,255,0.12)',  color: 'var(--accent)'  },
  };
  const s = styles[variant];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '3px 8px', borderRadius: 20, fontSize: 11, fontWeight: 600,
      background: s.bg, color: s.color,
    }}>
      {variant === 'active' && (
        <span style={{
          width: 5, height: 5, borderRadius: '50%', background: 'currentColor',
          animation: 'pulse 2s infinite',
        }} />
      )}
      {children}
    </span>
  );
}

// ---- Button ----
type BtnVariant = 'primary' | 'secondary' | 'danger' | 'ghost';
type BtnSize = 'sm' | 'md';

export function Btn({
  variant = 'secondary',
  size = 'md',
  children,
  onClick,
  disabled,
  type = 'button',
  style,
}: {
  variant?: BtnVariant;
  size?: BtnSize;
  children: React.ReactNode;
  onClick?: (e?: React.MouseEvent) => void;
  disabled?: boolean;
  type?: 'button' | 'submit' | 'reset';
  style?: React.CSSProperties;
}) {
  const base: React.CSSProperties = {
    display: 'inline-flex', alignItems: 'center', gap: 6,
    borderRadius: 'var(--radius)', fontFamily: 'inherit',
    fontWeight: 500, cursor: disabled ? 'not-allowed' : 'pointer',
    border: '1px solid transparent', transition: 'all 0.15s',
    opacity: disabled ? 0.5 : 1,
    padding: size === 'sm' ? '4px 10px' : '7px 14px',
    fontSize: size === 'sm' ? 12 : 13,
  };
  const variants: Record<BtnVariant, React.CSSProperties> = {
    primary:   { background: 'var(--accent)',                    color: '#fff' },
    secondary: { background: 'var(--surface-2)', borderColor: 'var(--border-2)', color: 'var(--text-1)' },
    danger:    { background: 'rgba(239,68,68,0.15)', borderColor: 'rgba(239,68,68,0.3)', color: 'var(--danger)' },
    ghost:     { background: 'transparent',          color: 'var(--text-2)' },
  };
  return (
    <button type={type} onClick={onClick} disabled={disabled} style={{ ...base, ...variants[variant], ...style }}>
      {children}
    </button>
  );
}

// ---- Card ----
export function Card({
  children,
  style,
  className,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
  className?: string;
}) {
  return (
    <div
      className={className}
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)',
        padding: 20,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// ---- CardTitle ----
export function CardTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 600, textTransform: 'uppercase',
      letterSpacing: '0.08em', color: 'var(--text-2)', marginBottom: 12,
    }}>
      {children}
    </div>
  );
}

// ---- StatCard ----
export function StatCard({
  label,
  value,
  delta,
  deltaDir,
  progress,
  progressVariant = 'accent',
}: {
  label: string;
  value: string | number;
  delta?: string;
  deltaDir?: 'up' | 'down' | 'neutral';
  progress?: number;
  progressVariant?: 'accent' | 'success' | 'warning' | 'danger' | 'info';
}) {
  const deltaColor = deltaDir === 'up' ? 'var(--success)' : deltaDir === 'down' ? 'var(--danger)' : 'var(--text-2)';
  const progressColors: Record<string, string> = {
    accent: 'var(--accent)', success: 'var(--success)',
    warning: 'var(--warning)', danger: 'var(--danger)', info: 'var(--accent)',
  };
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius-lg)', padding: 20,
    }}>
      <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-2)', marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, letterSpacing: '-0.03em', fontFamily: 'JetBrains Mono, monospace' }}>
        {value}
      </div>
      {delta && (
        <div style={{ fontSize: 12, marginTop: 6, color: deltaColor }}>
          {deltaDir === 'up' ? '↑' : deltaDir === 'down' ? '↓' : ''} {delta}
        </div>
      )}
      {progress !== undefined && (
        <div style={{ marginTop: 10, height: 4, background: 'var(--surface-2)', borderRadius: 2, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${Math.min(100, progress)}%`, background: progressColors[progressVariant], borderRadius: 2, transition: 'width 0.5s ease' }} />
        </div>
      )}
    </div>
  );
}

// ---- ProgressBar ----
export function ProgressBar({ value, variant = 'accent' }: { value: number; variant?: string }) {
  const colors: Record<string, string> = {
    accent: 'var(--accent)', success: 'var(--success)',
    warning: 'var(--warning)', danger: 'var(--danger)',
  };
  return (
    <div style={{ height: 4, background: 'var(--surface-2)', borderRadius: 2, overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${Math.min(100, value)}%`, background: colors[variant] || colors.accent, borderRadius: 2, transition: 'width 0.5s ease' }} />
    </div>
  );
}

// ---- Spinner ----
export function Spinner({ size = 20 }: { size?: number }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      border: `2px solid var(--border-2)`,
      borderTopColor: 'var(--accent)',
      animation: 'spin 0.7s linear infinite',
    }} />
  );
}

// ---- Empty state ----
export function EmptyState({ message, icon }: { message: string; icon?: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '48px 24px', color: 'var(--text-3)' }}>
      {icon && <div style={{ marginBottom: 12, opacity: 0.5 }}>{icon}</div>}
      <div style={{ fontSize: 13 }}>{message}</div>
    </div>
  );
}

// ---- Table ----
export function Table({ headers, children }: { headers: string[]; children: React.ReactNode }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h} style={{
                padding: '10px 12px', textAlign: 'left',
                fontSize: 11, fontWeight: 600, textTransform: 'uppercase',
                letterSpacing: '0.06em', color: 'var(--text-3)',
                borderBottom: '1px solid var(--border)',
              }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Tr({ children, onClick }: { children: React.ReactNode; onClick?: () => void }) {
  return (
    <tr
      onClick={onClick}
      style={{
        borderBottom: '1px solid var(--border)',
        cursor: onClick ? 'pointer' : 'default',
        transition: 'background 0.1s',
      }}
      onMouseEnter={e => { if (onClick) (e.currentTarget as HTMLElement).style.background = 'var(--surface-2)'; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
    >
      {children}
    </tr>
  );
}

export function Td({ children, mono }: { children: React.ReactNode; mono?: boolean }) {
  return (
    <td style={{
      padding: '12px 12px',
      fontFamily: mono ? 'JetBrains Mono, monospace' : 'inherit',
      fontSize: mono ? 12 : 13,
      color: 'var(--text-1)',
    }}>
      {children}
    </td>
  );
}

// ---- Input ----
export function Input({
  value, onChange, placeholder, type = 'text', label,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  label?: string;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      {label && <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--text-2)', marginBottom: 6 }}>{label}</label>}
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          width: '100%', padding: '8px 12px',
          background: 'var(--surface-2)', border: '1px solid var(--border-2)',
          borderRadius: 'var(--radius)', color: 'var(--text-1)',
          fontSize: 13, fontFamily: 'inherit', outline: 'none',
        }}
      />
    </div>
  );
}

// ---- Textarea ----
export function Textarea({
  value, onChange, placeholder, label, rows = 4,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  label?: string;
  rows?: number;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      {label && <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--text-2)', marginBottom: 6 }}>{label}</label>}
      <textarea
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        style={{
          width: '100%', padding: '8px 12px',
          background: 'var(--surface-2)', border: '1px solid var(--border-2)',
          borderRadius: 'var(--radius)', color: 'var(--text-1)',
          fontSize: 13, fontFamily: 'inherit', outline: 'none', resize: 'vertical',
        }}
      />
    </div>
  );
}
