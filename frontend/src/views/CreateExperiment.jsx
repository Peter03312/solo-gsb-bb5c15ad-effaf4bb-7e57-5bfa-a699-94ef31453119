import React, { useState } from 'react'
import { api } from '../api.js'

const EMPTY_ROW = () => ({
  code: '',
  concentration: '',
  available_volume: '',
  target_dose: '',
  index_sequence: '',
})

export default function CreateExperiment({ onCancel, onCreated, showError }) {
  const [name, setName] = useState('')
  const [availablePools, setAvailablePools] = useState(4)
  const [poolCapacity, setPoolCapacity] = useState('100')
  const [minPipette, setMinPipette] = useState('1')
  const [rows, setRows] = useState([EMPTY_ROW(), EMPTY_ROW(), EMPTY_ROW()])
  const [submitting, setSubmitting] = useState(false)

  const updateRow = (i, key, value) => {
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, [key]: value } : r)))
  }

  const validate = () => {
    if (!name.trim()) return '请填写计划名称'
    if (!(Number(availablePools) > 0)) return '可用池数必须为正整数'
    if (!(Number(poolCapacity) > 0)) return '单池体积上限必须为正数'
    if (!(Number(minPipette) > 0)) return '移液量下限必须为正数'
    if (Number(minPipette) > Number(poolCapacity))
      return '移液量下限不能大于单池体积上限'
    const codes = new Set()
    for (const [i, r] of rows.entries()) {
      if (!r.code.trim()) return `第 ${i + 1} 行：样本编号不能为空`
      if (codes.has(r.code.trim())) return `样本编号重复：${r.code.trim()}`
      codes.add(r.code.trim())
      for (const [label, key] of [
        ['浓度', 'concentration'],
        ['可用体积', 'available_volume'],
        ['目标投料量', 'target_dose'],
      ]) {
        if (!(Number(r[key]) > 0))
          return `第 ${i + 1} 行（${r.code}）：${label}必须为正数`
      }
      if (!r.index_sequence.trim())
        return `第 ${i + 1} 行（${r.code}）：索引序列不能为空`
    }
    return null
  }

  const submit = async () => {
    const err = validate()
    if (err) {
      showError(err)
      return
    }
    setSubmitting(true)
    try {
      const created = await api.createExperiment({
        name: name.trim(),
        available_pools: Number(availablePools),
        pool_capacity: String(poolCapacity),
        min_pipette_volume: String(minPipette),
        samples: rows.map((r) => ({
          code: r.code.trim(),
          concentration: String(r.concentration),
          available_volume: String(r.available_volume),
          target_dose: String(r.target_dose),
          index_sequence: r.index_sequence.trim(),
        })),
      })
      onCreated(created.id)
    } catch (e) {
      showError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section>
      <div className="section-head">
        <h2>新建拼池计划</h2>
        <button className="btn" onClick={onCancel}>
          ← 返回列表
        </button>
      </div>

      <div className="card">
        <h3>计划参数</h3>
        <div className="form-grid">
          <label>
            计划名称
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            可用池数
            <input
              type="number"
              min="1"
              step="1"
              value={availablePools}
              onChange={(e) => setAvailablePools(e.target.value)}
            />
          </label>
          <label>
            单池体积上限 (µL)
            <input
              type="number"
              min="0"
              step="any"
              value={poolCapacity}
              onChange={(e) => setPoolCapacity(e.target.value)}
            />
          </label>
          <label>
            移液量下限 (µL)
            <input
              type="number"
              min="0"
              step="any"
              value={minPipette}
              onChange={(e) => setMinPipette(e.target.value)}
            />
          </label>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h3>样本录入（{rows.length}）</h3>
          <div>
            <button className="btn small" onClick={() => setRows((rs) => [...rs, EMPTY_ROW()])}>
              + 添加一行
            </button>
            <button
              className="btn small"
              onClick={() => setRows((rs) => (rs.length > 1 ? rs.slice(0, -1) : rs))}
            >
              − 删除末行
            </button>
          </div>
        </div>
        <div className="table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th>#</th>
                <th>样本编号</th>
                <th>浓度</th>
                <th>可用体积 (µL)</th>
                <th>目标投料量</th>
                <th>索引序列</th>
                <th>理论取液量</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const tv =
                  Number(r.concentration) > 0 && r.target_dose !== ''
                    ? (Number(r.target_dose) / Number(r.concentration)).toFixed(4)
                    : '—'
                return (
                  <tr key={i}>
                    <td>{i + 1}</td>
                    <td>
                      <input
                        value={r.code}
                        placeholder={`S${i + 1}`}
                        onChange={(e) => updateRow(i, 'code', e.target.value)}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        min="0"
                        step="any"
                        value={r.concentration}
                        onChange={(e) => updateRow(i, 'concentration', e.target.value)}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        min="0"
                        step="any"
                        value={r.available_volume}
                        onChange={(e) => updateRow(i, 'available_volume', e.target.value)}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        min="0"
                        step="any"
                        value={r.target_dose}
                        onChange={(e) => updateRow(i, 'target_dose', e.target.value)}
                      />
                    </td>
                    <td>
                      <input
                        className="mono"
                        value={r.index_sequence}
                        placeholder="ACGT…（双索引用 - 分隔）"
                        onChange={(e) => updateRow(i, 'index_sequence', e.target.value)}
                      />
                    </td>
                    <td className="mono">{tv}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="actions">
        <button className="btn primary big" disabled={submitting} onClick={submit}>
          {submitting ? '求解中…' : '计算最优拼池方案'}
        </button>
      </div>
    </section>
  )
}
