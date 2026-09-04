import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export function Toggle({ on, onChange, disabled }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean }): JSX.Element {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      className={`toggle ${on ? 'on' : ''}`}
      disabled={disabled}
      onClick={() => onChange(!on)}
    />
  )
}

export function Modal({ title, children, onClose, actions }: { title: string; children: React.ReactNode; onClose?: () => void; actions?: React.ReactNode }): JSX.Element {
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className="modal" role="dialog" aria-modal="true">
        <h3>{title}</h3>
        {children}
        {actions ? <div className="actions">{actions}</div> : null}
      </div>
    </div>
  )
}

export function Markdown({ text }: { text: string }): JSX.Element {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a
              href={href}
              onClick={(e) => {
                e.preventDefault()
                if (href) window.iris.openExternal(href)
              }}
            >
              {children}
            </a>
          )
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }): JSX.Element {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint ? <span className="hint">{hint}</span> : null}
    </label>
  )
}

export function SettingRow({ title, desc, children }: { title: string; desc?: string; children: React.ReactNode }): JSX.Element {
  return (
    <div className="row between" style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
      <div style={{ minWidth: 0 }}>
        <div>{title}</div>
        {desc ? <div className="small muted">{desc}</div> : null}
      </div>
      <div className="row" style={{ flex: 'none' }}>{children}</div>
    </div>
  )
}
