import React, { useState } from 'react'
import { api } from '../api.js'

const TRIGGER_LABEL = {
  create: '首次计算',
  remeasure: '复测重算',
  add_samples: '追加样本',
}

export default function VersionPanel({ experimentId, versions, showError }) {
  const [openVersion, setOpenVersion] = useState(null)
  const [snapshot, setSnapshot] = useState(null)
  const [loading, setLoading] = useState(false)

  const open = async (no) => {
    setLoading(true)
    setOpenVersion(no)
    try {
      const v = await api.getVersion(experimentId, no)
      setSnapshot(v.snapshot)
    } catch (e) {
      showError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="side-panel">
      <p className="muted">
        每次计算都会生成不可变版本快照。锁定池在各版本中始终保留当时的配方。
      </p>
      <ul className="version-list">
        {versions.map((v) => (
          <li key={v.version_no}>
            <button className="version-item" onClick={() => open(v.version_no)}>
              <span className="version-no">v{v.version_no}</span>
              <span className="version-trigger">
                {TRIGGER_LABEL[v.trigger] ?? v.trigger}
                {v.proven_optimal === false && (
                  <span className="badge nonopt" title="满足硬约束但未证明最优">
                    未证明最优
                  </span>
                )}
              </span>
              <span className="version-stat">
                {v.arranged_count} 样本 / {v.pool_count} 池
              </span>
              <span className="version-time">{new Date(v.created_at).toLocaleString()}</span>
            </button>
          </li>
        ))}
      </ul>

      {openVersion != null && (
        <div className="modal-backdrop" onClick={() => setOpenVersion(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3>
                版本 v{openVersion} 快照
                {snapshot && snapshot.proven_optimal === false && (
                  <span className="badge nonopt">满足硬约束，未证明最优</span>
                )}
              </h3>
              <button className="btn small" onClick={() => setOpenVersion(null)}>
                关闭
              </button>
            </div>
            {loading || !snapshot ? (
              <p>加载中…</p>
            ) : (
              <div>
                <p className="muted">
                  池上限 {snapshot.params.pool_capacity} µL ｜ 移液下限{' '}
                  {snapshot.params.min_pipette_volume} µL ｜ 可用池数{' '}
                  {snapshot.params.available_pools}
                </p>
                {snapshot.pools.map((p) => (
                  <div key={p.position} className={`mini-pool ${p.locked ? 'locked' : ''}`}>
                    <div className="mini-pool-head">
                      池 {p.position}
                      {p.locked && <span className="badge lock">🔒 锁定配方</span>}
                      <span className="mono">合计 {p.total_volume} µL</span>
                    </div>
                    <table className="table compact">
                      <tbody>
                        {p.members.map((m) => (
                          <tr key={m.sample_id}>
                            <td>{m.code}</td>
                            <td className="mono">{m.index_sequence}</td>
                            <td className="mono">
                              浓度 {m.concentration} → 取液 {m.take_volume}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))}
                {snapshot.unarranged.length > 0 && (
                  <div className="mini-unarranged">
                    <b>未安排：</b>
                    {snapshot.unarranged.map((u) => (
                      <div key={u.sample_id} className="reason">
                        {u.code}：{u.reason}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
