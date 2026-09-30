import React from 'react'

const TRIGGER_LABEL = {
  manual: '手动生成',
  add_samples: '新增样本后重算',
  delete_sample: '删除样本后重算',
  unlock: '解锁池后重算',
  remeasure: '复测浓度后重算',
  remeasure_locked: '复测（锁定池，配方保留）',
}

export default function PoolsPanel({ batch, onLock, onUnlock, busy }) {
  const { summary, pools, unassigned, versions, num_pools } = batch
  if (!summary) return null

  return (
    <>
      <div className="panel">
        <h2>
          配液方案
          <span className="badge badge-blue">v{summary.version}</span>
          <span className="hint">
            {TRIGGER_LABEL[summary.trigger] || summary.trigger} · {summary.created_at}
          </span>
        </h2>

        <div className="stat-row">
          <div className="stat">
            <div className="v">{summary.assigned}/{summary.total_samples}</div>
            <div className="k">已安排 / 样本总数</div>
          </div>
          <div className="stat">
            <div className="v">{summary.pools_used}/{num_pools}</div>
            <div className="k">已用池 / 可用池</div>
          </div>
          <div className="stat">
            <div className="v" style={{ color: 'var(--lock)' }}>{summary.pools_locked}</div>
            <div className="k">已锁定池</div>
          </div>
          <div className="stat">
            <div className="v" style={{ color: summary.unassigned ? 'var(--red)' : 'var(--green)' }}>
              {summary.unassigned}
            </div>
            <div className="k">未安排样本</div>
          </div>
        </div>

        {Array.isArray(summary.warnings) && summary.warnings.length > 0 && (
          <div className="alert alert-warn">
            <b>⚠️ 警示</b>
            <ul>{summary.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
          </div>
        )}

        <div className="pool-grid">
          {pools.map((p) => (
            <div key={p.pool_no} className={`pool-card${p.locked ? ' locked' : ''}`}>
              <div className="pool-head">
                <span className="title">池 {p.pool_no}</span>
                {p.locked
                  ? <span className="badge badge-purple">🔒 已锁定</span>
                  : <span className="badge badge-green">未锁定</span>}
                <span className="spacer" />
                {p.locked ? (
                  <button className="btn-sm btn-unlock" disabled={busy}
                    onClick={() => onUnlock(p.pool_no)}>
                    解锁并重算
                  </button>
                ) : (
                  <button className="btn-sm btn-lock" disabled={busy}
                    onClick={() => onLock(p.pool_no)}>
                    锁定配方
                  </button>
                )}
              </div>
              <div className="pool-body">
                <table>
                  <thead>
                    <tr>
                      <th>样本</th><th>索引</th>
                      <th className="num">浓度</th><th className="num">投料(ng)</th>
                      <th className="num">取液(µL)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.items.map((it) => {
                      const stale = p.locked &&
                        it.concentration_current != null &&
                        Math.abs(it.concentration_current - it.concentration) > 1e-9
                      return (
                        <tr key={it.sample_id}>
                          <td>
                            {it.name}
                            {stale && (
                              <div className="stale">
                                复测 {it.concentration}→{it.concentration_current}，本池仍按原配方
                              </div>
                            )}
                          </td>
                          <td className="mono">{it.index_seq}</td>
                          <td className="num">{it.concentration}</td>
                          <td className="num">{it.target_amount}</td>
                          <td className="num"><b>{Number(it.transfer_volume).toFixed(3)}</b></td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <div className="pool-foot">
                <span>合计取液：<b>{Number(p.total_volume).toFixed(3)} µL</b> / 上限 {batch.max_pool_volume}</span>
                <span>{p.items.length} 个样本</span>
              </div>
              {p.locked && p.locked_at && (
                <div className="pool-foot" style={{ background: '#f7f3fe' }}>
                  <span>锁定时间 {p.locked_at}</span>
                  <span>锁定后复测仅警示，不改此池</span>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <h2>
          未安排样本
          <span className="hint">系统不会为无法满足约束的样本生成虚假配方</span>
        </h2>
        {unassigned.length === 0 ? (
          <p className="muted">✅ 全部样本均已安排，无未满足约束。</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>样本</th><th>索引</th>
                  <th className="num">浓度</th><th className="num">计算取液量(µL)</th>
                  <th>未安排原因</th>
                </tr>
              </thead>
              <tbody>
                {unassigned.map((u) => (
                  <tr key={u.sample_id ?? u.name}>
                    <td><b>{u.name}</b></td>
                    <td className="mono">{u.index_seq}</td>
                    <td className="num">{u.concentration}</td>
                    <td className="num">{Number(u.transfer_need).toFixed(3)}</td>
                    <td>
                      <ul style={{ margin: 0, paddingLeft: 18 }}>
                        {u.reasons.map((r, i) => <li key={i} style={{ color: 'var(--red)' }}>{r}</li>)}
                      </ul>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel">
        <h2>版本记录</h2>
        <ul className="timeline">
          {versions.map((v) => (
            <li key={v.version}>
              <span className="ver">v{v.version}</span>
              <span className="badge badge-blue" style={{ marginLeft: 8 }}>
                {TRIGGER_LABEL[v.trigger] || v.trigger}
              </span>
              <span className="time">{v.created_at}</span>
              <div className="muted" style={{ marginTop: 4 }}>{v.note}</div>
              {v.warnings.length > 0 && (
                <div className="alert alert-warn mt" style={{ marginBottom: 0 }}>
                  <ul>{v.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
                </div>
              )}
            </li>
          ))}
        </ul>
      </div>
    </>
  )
}
