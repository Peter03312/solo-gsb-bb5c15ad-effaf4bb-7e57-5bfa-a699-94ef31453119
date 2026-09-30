import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import PoolCard from '../components/PoolCard.jsx'
import RemeasurePanel from '../components/RemeasurePanel.jsx'
import AddSamplesPanel from '../components/AddSamplesPanel.jsx'
import VersionPanel from '../components/VersionPanel.jsx'

export default function ExperimentDetail({ id, onBack, showError }) {
  const [data, setData] = useState(null)
  const [tab, setTab] = useState('remeasure')

  const load = useCallback(async () => {
    try {
      setData(await api.getExperiment(id))
    } catch (e) {
      showError(e.message)
    }
  }, [id, showError])

  useEffect(() => {
    load()
  }, [load])

  if (!data) return <p>加载中…</p>

  const lockedCount = data.pools.filter((p) => p.locked).length
  const affectedLocked = data.pools.some(
    (p) => p.locked && p.warnings && p.warnings.length > 0
  )
  const currentVersionInfo = data.versions.find(
    (v) => v.version_no === data.current_version
  )
  const notProven = currentVersionInfo && currentVersionInfo.proven_optimal === false

  return (
    <section>
      <div className="section-head">
        <h2>{data.name}</h2>
        <button className="btn" onClick={onBack}>
          ← 返回列表
        </button>
      </div>

      <div className="card params">
        <div>
          <span className="param-label">可用池数</span>
          <span className="param-value">{data.available_pools}</span>
        </div>
        <div>
          <span className="param-label">单池体积上限</span>
          <span className="param-value">{data.pool_capacity} µL</span>
        </div>
        <div>
          <span className="param-label">移液量下限</span>
          <span className="param-value">{data.min_pipette_volume} µL</span>
        </div>
        <div>
          <span className="param-label">当前版本</span>
          <span className="param-value">v{data.current_version}</span>
        </div>
        <div>
          <span className="param-label">已安排</span>
          <span className="param-value">
            <span className="ok">
              {data.pools.reduce((n, p) => n + p.assignments.length, 0)}
            </span>
            {' / '}
            {data.samples.length} 个样本
          </span>
        </div>
        <div>
          <span className="param-label">锁定池</span>
          <span className={`param-value ${affectedLocked ? 'warn' : ''}`}>
            {lockedCount} / {data.pools.length}
            {affectedLocked ? '（有警示）' : ''}
          </span>
        </div>
      </div>

      {notProven && (
        <div className="card notice">
          ⏱️ 当前 v{data.current_version} 方案满足全部硬约束（容量、索引唯一、移液下限、
          可用体积），但样本规模较大，求解器在限定时间内<b>未能证明</b>它已是
          “安排样本数最多、池数最少”的最优解；下列配液表可直接使用，同时可能还存在能
          多安排样本的方案。可调大服务端 <code>SOLVER_TIME_LIMIT</code> 后重新复测以获得
          更长求解时间。
        </div>
      )}

      <div className="layout">
        <div className="layout-main">
          <h3 className="block-title">
            各池配液表（{data.pools.length} 个池）
          </h3>
          {data.pools.length === 0 && (
            <div className="empty">
              当前没有生成任何池 —— 没有样本同时满足取液量下限、可用体积与单池体积上限。
            </div>
          )}
          {data.pools.map((p) => (
            <PoolCard
              key={p.pool_id}
              pool={p}
              capacity={data.pool_capacity}
              onLock={async (locked) => {
                try {
                  setData(await api.setLock(id, p.position, locked))
                } catch (e) {
                  showError(e.message)
                }
              }}
            />
          ))}

          {data.unarranged.length > 0 && (
            <div className="card unarranged">
              <h3>未安排样本（{data.unarranged.length}）</h3>
              <p className="muted">
                以下样本未进入任何池，系统不会为其生成配方；原因如下：
              </p>
              <table className="table compact">
                <thead>
                  <tr>
                    <th>样本编号</th>
                    <th>索引序列</th>
                    <th>浓度</th>
                    <th>目标投料量</th>
                    <th>理论取液量</th>
                    <th>未安排原因</th>
                  </tr>
                </thead>
                <tbody>
                  {data.unarranged.map((a) => (
                    <tr key={a.sample_id}>
                      <td>{a.code}</td>
                      <td className="mono">{a.index_sequence}</td>
                      <td>{a.concentration}</td>
                      <td>{a.target_dose}</td>
                      <td className="mono">{a.take_volume ?? '—'}</td>
                      <td className="reason">{a.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <aside className="layout-side">
          <div className="tabs">
            <button
              className={tab === 'remeasure' ? 'tab active' : 'tab'}
              onClick={() => setTab('remeasure')}
            >
              复测浓度
            </button>
            <button
              className={tab === 'add' ? 'tab active' : 'tab'}
              onClick={() => setTab('add')}
            >
              追加样本
            </button>
            <button
              className={tab === 'versions' ? 'tab active' : 'tab'}
              onClick={() => setTab('versions')}
            >
              版本记录
            </button>
          </div>

          {tab === 'remeasure' && (
            <RemeasurePanel
              experimentId={id}
              samples={data.samples}
              onDone={(updated) => {
                setData(updated)
              }}
              showError={showError}
            />
          )}
          {tab === 'add' && (
            <AddSamplesPanel
              experimentId={id}
              onDone={setData}
              showError={showError}
            />
          )}
          {tab === 'versions' && (
            <VersionPanel experimentId={id} versions={data.versions} showError={showError} />
          )}
        </aside>
      </div>
    </section>
  )
}
