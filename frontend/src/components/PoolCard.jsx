import React, { useState } from 'react'

/** 单个池的配液表卡片：池号、锁定状态、总体积、成员取液量与警示。 */
export default function PoolCard({ pool, capacity, onLock }) {
  const [busy, setBusy] = useState(false)
  const overCap = Number(pool.total_volume) > Number(capacity)

  const toggle = async () => {
    setBusy(true)
    try {
      await onLock(!pool.locked)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`card pool ${pool.locked ? 'locked' : ''}`}>
      <div className="pool-head">
        <div>
          <span className="pool-no">池 {pool.position}</span>
          {pool.locked && <span className="badge lock">🔒 已锁定 · 配方 v{pool.version_no}</span>}
          {!pool.locked && <span className="badge unlocked">未锁定 · 来自 v{pool.version_no}</span>}
        </div>
        <div className="pool-meta">
          <div>
            总体积：
            <strong className={overCap ? 'warn mono' : 'ok mono'}>
              {pool.total_volume}
            </strong>
            {' '}/ {capacity} µL
          </div>
          <button className="btn small" disabled={busy} onClick={toggle}>
            {pool.locked ? '解锁（下次重算将参与）' : '锁定配方'}
          </button>
        </div>
      </div>

      {pool.warnings?.length > 0 && (
        <ul className="warnings">
          {pool.warnings.map((w, i) => (
            <li key={i}>⚠️ {w}</li>
          ))}
        </ul>
      )}

      <div className="table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>样本编号</th>
              <th>索引序列</th>
              <th>浓度</th>
              <th>目标投料量</th>
              <th>取液量 (µL)</th>
            </tr>
          </thead>
          <tbody>
            {pool.assignments.map((a) => (
              <tr key={a.sample_id}>
                <td>{a.code}</td>
                <td className="mono">{a.index_sequence}</td>
                <td>{a.concentration}</td>
                <td>{a.target_dose}</td>
                <td className="mono strong">{a.take_volume}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
