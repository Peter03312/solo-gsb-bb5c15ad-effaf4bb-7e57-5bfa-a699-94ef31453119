import React, { useEffect, useState, useCallback } from 'react'
import { api } from './api.js'
import Workbench from './Workbench.jsx'

export function ErrorAlert({ error, onClose }) {
  if (!error) return null
  return (
    <div className="alert alert-error">
      <div className="flex">
        <span>⚠️ {error.message || String(error)}</span>
        <span className="spacer" />
        {onClose && (
          <button className="btn-sm" onClick={onClose}>
            关闭
          </button>
        )}
      </div>
    </div>
  )
}

function BatchList({ onOpen }) {
  const [batches, setBatches] = useState([])
  const [error, setError] = useState(null)
  const [form, setForm] = useState({
    name: '',
    num_pools: '4',
    max_pool_volume: '100',
    min_transfer: '1',
  })
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setBatches(await api.listBatches())
    } catch (e) {
      setError(e)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const create = async (e) => {
    e.preventDefault()
    setError(null)
    const num_pools = Number(form.num_pools)
    const max_pool_volume = Number(form.max_pool_volume)
    const min_transfer = Number(form.min_transfer)
    if (!(num_pools > 0) || !(max_pool_volume > 0) || !(min_transfer > 0)) {
      setError(new Error('可用池数、单池体积上限、移液量下限均须为正数'))
      return
    }
    if (!form.name.trim()) {
      setError(new Error('批次名称不能为空'))
      return
    }
    setBusy(true)
    try {
      const b = await api.createBatch({
        name: form.name.trim(),
        num_pools,
        max_pool_volume,
        min_transfer,
      })
      onOpen(b.id)
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (e, id) => {
    e.stopPropagation()
    if (!window.confirm('确定删除该批次及其全部方案？此操作不可恢复。')) return
    await api.deleteBatch(id)
    load()
  }

  return (
    <div>
      <div className="panel">
        <h2>新建拼池批次</h2>
        <ErrorAlert error={error} onClose={() => setError(null)} />
        <form onSubmit={create}>
          <div className="grid-form">
            <label className="field">
              <span className="lbl">批次名称</span>
              <input value={form.name} onChange={set('name')} placeholder="如 NGS-20260930-A" />
            </label>
            <label className="field">
              <span className="lbl">可用池数（个，正整数）</span>
              <input type="number" step="1" min="1" value={form.num_pools} onChange={set('num_pools')} />
            </label>
            <label className="field">
              <span className="lbl">单池体积上限（µL）</span>
              <input type="number" step="any" min="0" value={form.max_pool_volume} onChange={set('max_pool_volume')} />
            </label>
            <label className="field">
              <span className="lbl">移液量下限（µL）</span>
              <input type="number" step="any" min="0" value={form.min_transfer} onChange={set('min_transfer')} />
            </label>
          </div>
          <button className="btn-primary" disabled={busy}>
            {busy ? '创建中…' : '创建批次'}
          </button>
        </form>
      </div>

      <div className="panel">
        <h2>
          批次列表 <span className="hint">共 {batches.length} 个</span>
        </h2>
        {batches.length === 0 && <p className="muted">暂无批次，请先创建。</p>}
        {batches.map((b) => (
          <div key={b.id} className="batch-card" onClick={() => onOpen(b.id)}>
            <div>
              <div className="name">{b.name}</div>
              <div className="meta">
                池 {b.num_pools} 个 · 单池上限 {b.max_pool_volume} µL · 移液下限 {b.min_transfer} µL ·
                样本 {b.sample_count} 个
              </div>
            </div>
            <span className="spacer" />
            {b.has_plan && (
              <span className="badge badge-blue">v{b.version}</span>
            )}
            {b.locked_count > 0 && (
              <span className="badge badge-purple">🔒 {b.locked_count} 池已锁定</span>
            )}
            <button className="btn-sm btn-danger" onClick={(e) => remove(e, b.id)}>
              删除
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function App() {
  const [openId, setOpenId] = useState(null)

  return (
    <>
      <header className="app-header">
        <span style={{ fontSize: 22 }}>🧬</span>
        <div>
          <h1>测序样本拼池工作台</h1>
          <div className="sub">样本浓度 / 体积 / 目标投料 / 索引录入 · 最优拼池 · 复测重算 · 池锁定</div>
        </div>
        <span className="spacer" />
        {openId && (
          <button onClick={() => setOpenId(null)}>返回批次列表</button>
        )}
      </header>
      <div className="container">
        {openId ? (
          <Workbench key={openId} batchId={openId} onBack={() => setOpenId(null)} />
        ) : (
          <BatchList onOpen={setOpenId} />
        )}
      </div>
    </>
  )
}
