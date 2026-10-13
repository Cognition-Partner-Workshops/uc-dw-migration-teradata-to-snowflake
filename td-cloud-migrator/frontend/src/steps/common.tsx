import type { ReactNode } from 'react'
import { STATUS_LABEL } from './format'


export function Badge({ status, children }: { status: string; children?: ReactNode }) {
  return <span className={`badge ${status}`}>{children ?? STATUS_LABEL[status] ?? status}</span>
}

export function Card({ title, children, extra }: { title: string; children: ReactNode; extra?: ReactNode }) {
  return (
    <section className="card">
      <div className="card-head">
        <h2>{title}</h2>
        {extra}
      </div>
      {children}
    </section>
  )
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className={`stat ${tone ?? ''}`}>
      <div className="value">{value}</div>
      <div className="label">{label}</div>
    </div>
  )
}
