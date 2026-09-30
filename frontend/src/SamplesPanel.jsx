import React, { useState } from 'react'

const BULK_HELP =
  '每行一个样本，用制表符或逗号分隔：名称, 浓度, 可用体积, 目标投料量, 索引序列\n' +
  '示例：S1\t2.5\t40\t5\tATCACG'

function posNumber(v) {
  const n = Number(v)
  return Number.isFinite(n) && n > 0 ? n : NaN
}

export function parseBulk(text) {
  const rows = text.split(/\r?\n/).map((r) => r.trim()).filter(Boolean)
  const samples = []
  const errors = []
  const names = new Set()
  rows.forEach((line, i) => {
    const parts = line.split(/[\t,，;；]+/).map((x) => x.trim())
    if (parts.length !== 5) {
      errors.push(`第 ${i + 1} 行：应为 5 列（名称,浓度,可用体积,目标投料,索引），实际 ${parts.length} 列`)
      return
    }
    const [name, conc, avail, target, index_seq] = parts
    const concentration = posNumber(conc)
    const available_volume = posNumber(avail)
    const target_amount = posNumber(target)
    const rowErr = []
    if (!name) rowErr.push('名称为空')
    if (Number.isNaN(concentration)) rowErr.push('浓度须为正数')
    if (Number.isNaN(available_volume)) rowErr.push('可用体积须为正数')
    if (Number.isNaN(target_amount)) rowErr.push('目标投料量须为正数')
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(index_seq)) rowErr.push('索引格式不合法')
    if (names.has(name)) rowErr.push('批次内名称重复')
    if (rowErr.length) {
      errors.push(`第 ${i + 1} 行（${name || '未命名'}）：${rowErr.join('、')}`)
      return
    }
    names.add(name)
    samples.push({ name, concentration, available_volume, target_amount, index_seq })
  })
  return { samples, errors }
}

export default function SamplesPanel({ batch, onAdd, onDelete, onRemeasure, busy }) {
  const [bulkOpen, setBulkOpen] = useState(false)
  const [bulkText, setBulkText] = useState('')
  const [bulkErrors, setBulkErrors] = useState([])
  const [f, setF] = useState({ name: '', concentration: '', available_volume: '', target_amount: '', index_seq: '' })
  const [formErr, setFormErr] = useState(null)
  const [remeasuring, setRemeasuring] = useState({}) // sampleId -> string
  const cap = batch.max_pool_volume
  const minT = batch.min_transfer

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const addOne = async (e) => {
    e.preventDefault()
    setFormErr(null)
    const concentration = posNumber(f.concentration)
    const available_volume = posNumber(f.available_volume)
    const target_amount = posNumber(f.target_amount)
    const errs = []
    if (!f.name.trim()) errs.push('名称不能为空')
    if (Number.isNaN(concentration)) errs.push('浓度须为正数')
    if (Number.isNaN(available_volume)) errs.push('可用体积须为正数')
    if (Number.isNaN(target_amount)) errs.push('目标投料量须为正数')
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(f.index_seq.trim())) errs.push('索引格式不合法')
    if (batch.samples.some((s) => s.name === f.name.trim())) errs.push('名称与已有样本重复')
    if (errs.length) {
      setFormErr(new Error(errs.join('；')))
      return
    }
    await onAdd([
      { name: f.name.trim(), concentration, available_volume, target_amount, index_seq: f.index_seq.trim() },
    ])
    setF({ name: '', concentration: '', available_volume: '', target_amount: '', index_seq: '' })
  }

  const submitBulk = async () => {
    const { samples, errors } = parseBulk(bulkText)
    const dup = samples.filter((s) => batch.samples.some((x) => x.name === s.name)).map((s) => s.name)
    if (dup.length) errors.push(`与已有样本重名：${dup.join('、')}`)
    setBulkErrors(errors)
    if (errors.length || !samples.length) return
    await onAdd(samples)
    setBulkText('')
    setBulkOpen(false)
  }

  const submitRemeasure = async (sid) => {
    const v = posNumber(remeasuring[sid])
    if (Number.isNaN(v)) {
      window.alert('复测浓度须为正数')
      return
    }
    await onRemeasure(sid, v)
    setRemeasuring({ ...remeasuring, [sid]: '' })
  }

  const need = f.concentration && f.target_amount
    ? Number(f.target_amount) / Number(f.concentration)
    : null

  return (
    <div className="panel">
      <h2>
        样本录入 <span className="hint">取液量 = 目标投料量 ÷ 浓度（µL = ng ÷ ng/µL）</span>
        <span className="spacer" />
        <button className="btn-sm" onClick={() => setBulkOpen(!bulkOpen)}>
          {bulkOpen ? '收起批量录入' : '📋 批量粘贴录入'}
        </button>
      </h2>

      {bulkOpen && (
        <div className="mb">
          <div className="muted mb" style={{ fontSize: 12.5 }}>{BULK_HELP}</div>
          <textarea
            className="bulk"
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
            placeholder={'S1\t2.5\t40\t5\tATCACG\nS2\t3.0\t30\t6\tCGATGT'}
          />
          {bulkErrors.length > 0 && (
            <div className="alert alert-error mt">
              <b>批量录入被拒绝：</b>
              <ul>{bulkErrors.map((er, i) => <li key={i}>{er}</li>)}</ul>
            </div>
          )}
          <div className="mt">
            <button className="btn-primary btn-sm" onClick={submitBulk} disabled={busy}>
              校验并加入 {parseBulk(bulkText).samples.length > 0 ? `（${parseBulk(bulkText).samples.length} 条）` : ''}
            </button>
          </div>
        </div>
      )}

      <form onSubmit={addOne} className="grid-form">
        <label className="field">
          <span className="lbl">样本名称</span>
          <input value={f.name} onChange={set('name')} placeholder="S1" />
        </label>
        <label className="field">
          <span className="lbl">浓度（ng/µL，&gt;0）</span>
          <input type="number" step="any" min="0" value={f.concentration} onChange={set('concentration')} />
        </label>
        <label className="field">
          <span className="lbl">可用体积（µL，&gt;0）</span>
          <input type="number" step="any" min="0" value={f.available_volume} onChange={set('available_volume')} />
        </label>
        <label className="field">
          <span className="lbl">目标投料量（ng，&gt;0）</span>
          <input type="number" step="any" min="0" value={f.target_amount} onChange={set('target_amount')} />
        </label>
        <label className="field">
          <span className="lbl">索引序列（Index）</span>
          <input value={f.index_seq} onChange={set('index_seq')} placeholder="ATCACG" className="mono" />
        </label>
        <div className="field" style={{ alignSelf: 'end' }}>
          <button className="btn-primary" disabled={busy}>加入样本</button>
        </div>
        {need !== null && Number.isFinite(need) && need > 0 && (
          <div className="field" style={{ alignSelf: 'end' }}>
            <div className="muted" style={{ fontSize: 12.5 }}>
              取液量 = <b style={{ color: 'var(--ink)' }}>{need.toFixed(3)} µL</b>
              {need < minT && <div className="stale">低于移液量下限 {minT}</div>}
              {need > Number(f.available_volume) && Number(f.available_volume) > 0 && (
                <div className="stale">超过可用体积</div>
              )}
              {need > cap && <div className="stale">超过单池体积上限 {cap}</div>}
            </div>
          </div>
        )}
      </form>
      {formErr && <div className="alert alert-error">⚠️ {formErr.message}</div>}

      <div className="table-wrap mt">
        <table>
          <thead>
            <tr>
              <th>名称</th>
              <th className="num">浓度</th>
              <th className="num">可用体积</th>
              <th className="num">目标投料</th>
              <th>索引</th>
              <th className="num">取液量</th>
              <th>状态</th>
              <th>复测浓度 / 操作</th>
            </tr>
          </thead>
          <tbody>
            {batch.samples.length === 0 && (
              <tr><td colSpan={8} className="muted" style={{ textAlign: 'center', padding: 18 }}>
                尚未录入样本
              </td></tr>
            )}
            {batch.samples.map((s) => {
              const need = s.target_amount / s.concentration
              const issues = []
              if (need < minT) issues.push(`低于移液量下限 ${minT}`)
              if (need > s.available_volume) issues.push('超过可用体积')
              if (need > cap) issues.push(`超过单池上限 ${cap}`)
              return (
                <tr key={s.id}>
                  <td><b>{s.name}</b></td>
                  <td className="num">{s.concentration}</td>
                  <td className="num">{s.available_volume}</td>
                  <td className="num">{s.target_amount}</td>
                  <td className="mono">{s.index_seq}</td>
                  <td className="num">{need.toFixed(3)}</td>
                  <td>
                    {issues.length
                      ? <span className="badge badge-red">{issues.join('；')}</span>
                      : <span className="badge badge-green">可安排</span>}
                  </td>
                  <td>
                    <div className="row-actions">
                      <input
                        className="inline-input mono"
                        type="number"
                        step="any"
                        min="0"
                        placeholder="复测浓度"
                        value={remeasuring[s.id] ?? ''}
                        onChange={(e) => setRemeasuring({ ...remeasuring, [s.id]: e.target.value })}
                      />
                      <button className="btn-sm btn-primary" disabled={busy}
                        onClick={() => submitRemeasure(s.id)}>
                        复测重算
                      </button>
                      <button className="btn-sm btn-danger" disabled={busy}
                        onClick={() => onDelete(s.id)}>
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
