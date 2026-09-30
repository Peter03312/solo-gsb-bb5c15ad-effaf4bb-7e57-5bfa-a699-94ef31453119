import React, { useState } from 'react'
import { api } from '../api.js'

const EMPTY = { code: '', concentration: '', available_volume: '', target_dose: '', index_sequence: '' }

export default function AddSamplesPanel({ experimentId, onDone, showError }) {
  const [rows, setRows] = useState([EMPTY])
  const [submitting, setSubmitting] = useState(false)

  const update = (i, key, value) =>
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, [key]: value } : r)))

  const submit = async () => {
    for (const [i, r] of rows.entries()) {
      if (!r.code.trim()) return showError(`第 ${i + 1} 行：样本编号不能为空`)
      for (const [label, key] of [
        ['浓度', 'concentration'],
        ['可用体积', 'available_volume'],
        ['目标投料量', 'target_dose'],
      ]) {
        if (!(Number(r[key]) > 0))
          return showError(`第 ${i + 1} 行（${r.code}）：${label}必须为正数`)
      }
      if (!r.index_sequence.trim())
        return showError(`第 ${i + 1} 行（${r.code}）：索引序列不能为空`)
    }
    setSubmitting(true)
    try {
      const updated = await api.addSamples(
        experimentId,
        rows.map((r) => ({
          code: r.code.trim(),
          concentration: String(r.concentration),
          available_volume: String(r.available_volume),
          target_dose: String(r.target_dose),
          index_sequence: r.index_sequence.trim(),
        }))
      )
      onDone(updated)
      setRows([EMPTY])
    } catch (e) {
      showError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="side-panel">
      <p className="muted">
        追加样本后，系统在保留锁定池的前提下，对所有未锁定池重新求最优方案。
      </p>
      {rows.map((r, i) => (
        <div className="add-row" key={i}>
          <input placeholder="样本编号" value={r.code}
            onChange={(e) => update(i, 'code', e.target.value)} />
          <input type="number" min="0" step="any" placeholder="浓度" value={r.concentration}
            onChange={(e) => update(i, 'concentration', e.target.value)} />
          <input type="number" min="0" step="any" placeholder="可用体积" value={r.available_volume}
            onChange={(e) => update(i, 'available_volume', e.target.value)} />
          <input type="number" min="0" step="any" placeholder="目标投料量" value={r.target_dose}
            onChange={(e) => update(i, 'target_dose', e.target.value)} />
          <input className="mono" placeholder="索引序列 ACGT…" value={r.index_sequence}
            onChange={(e) => update(i, 'index_sequence', e.target.value)} />
        </div>
      ))}
      <div className="row-actions">
        <button className="btn small" onClick={() => setRows((rs) => [...rs, EMPTY])}>
          + 一行
        </button>
        <button
          className="btn small"
          onClick={() => setRows((rs) => (rs.length > 1 ? rs.slice(0, -1) : rs))}
        >
          − 末行
        </button>
      </div>
      <button className="btn primary" disabled={submitting} onClick={submit}>
        {submitting ? '重算中…' : '追加并重算'}
      </button>
    </div>
  )
}
