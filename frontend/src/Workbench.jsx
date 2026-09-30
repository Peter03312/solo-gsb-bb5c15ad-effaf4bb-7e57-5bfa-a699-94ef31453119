import React, { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import SamplesPanel from './SamplesPanel.jsx'
import PoolsPanel from './PoolsPanel.jsx'
import { ErrorAlert } from './App.jsx'

export default function Workbench({ batchId, onBack }) {
  const [batch, setBatch] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async (flash) => {
    try {
      const d = await api.getBatch(batchId)
      setBatch(d)
      if (flash !== undefined) setNotice(flash)
    } catch (e) {
      setError(e)
    }
  }, [batchId])

  useEffect(() => {
    load()
  }, [load])

  const run = async (fn, okMsg) => {
    setBusy(true)
    setError(null)
    try {
      const r = await fn()
      if (r && Array.isArray(r.warnings) && r.warnings.length) {
        setNotice({ type: 'warn', lines: r.warnings })
      } else if (okMsg) {
        setNotice({ type: 'info', lines: [okMsg] })
      } else {
        setNotice(null)
      }
      await load()
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  if (!batch) {
    return (
      <div>
        <ErrorAlert error={error} />
        <p className="muted">加载中…</p>
      </div>
    )
  }

  const hasPlan = !!batch.summary
  const lockedSet = new Set(
    batch.pools.filter((p) => p.locked).flatMap((p) => p.items.map((i) => i.sample_id)),
  )

  return (
    <div>
      <div className="crumb">
        <a onClick={onBack}>批次列表</a> / <b>{batch.name}</b>
      </div>

      <div className="panel">
        <h2>批次参数</h2>
        <div className="flex flex-wrap" style={{ gap: 24 }}>
          <div>
            <div className="muted" style={{ fontSize: 12 }}>可用池数</div>
            <b>{batch.num_pools} 个</b>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 12 }}>单池体积上限</div>
            <b>{batch.max_pool_volume} µL</b>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 12 }}>移液量下限</div>
            <b>{batch.min_transfer} µL</b>
          </div>
          <span className="spacer" />
          <button
            className="btn-primary"
            disabled={busy || batch.samples.length === 0}
            onClick={() => run(() => api.plan(batchId), hasPlan ? '已重新生成方案' : '已生成方案')}
          >
            {hasPlan ? '重新生成配液方案（未锁定池重算）' : '生成配液方案'}
          </button>
        </div>
        <div className="muted mt" style={{ fontSize: 12.5 }}>
          优化目标：先最大化可安排样本数，再最小化使用池数（MILP 精确求解）。
          锁定池配方完全保留，重算只使用其余空池位。
        </div>
      </div>

      <ErrorAlert error={error} onClose={() => setError(null)} />
      {notice && (
        <div className={`alert ${notice.type === 'warn' ? 'alert-warn' : 'alert-info'}`}>
          {notice.lines.length === 1 ? notice.lines[0] : (
            <>
              <b>提示：</b>
              <ul>{notice.lines.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </>
          )}
        </div>
      )}

      <SamplesPanel
        batch={batch}
        busy={busy}
        onAdd={(samples) => run(() => api.addSamples(batchId, samples),
          `已加入 ${samples.length} 个样本${hasPlan ? '，未锁定池已重算' : ''}`)}
        onDelete={(sid) => {
          if (lockedSet.has(sid)) {
            setError(new Error('该样本属于已锁定池，请先解锁对应池'))
            return
          }
          if (!window.confirm('删除该样本？未锁定池将重新计算。')) return
          run(() => api.deleteSample(batchId, sid), '样本已删除，方案已重算')
        }}
        onRemeasure={(sid, conc) =>
          run(() => api.remeasure(batchId, sid, conc))}
      />

      {!hasPlan && (
        <div className="panel">
          <p className="muted">
            录入样本后点击上方「生成配液方案」。所有数量字段必须为正数，索引序列在同一池内不得重复。
          </p>
        </div>
      )}

      <PoolsPanel
        batch={batch}
        busy={busy}
        onLock={(no) => run(() => api.lock(batchId, no), `池 ${no} 已锁定，配方将保留`)}
        onUnlock={(no) => {
          if (!window.confirm(`解锁池 ${no}？其样本将重新参与全局拼池优化。`)) return
          run(() => api.unlock(batchId, no), `池 ${no} 已解锁，方案已重算`)
        }}
      />
    </div>
  )
}
