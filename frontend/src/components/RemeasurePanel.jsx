import React, { useState } from 'react'
import { api } from '../api.js'

/** 复测浓度录入：更新浓度（可选更新可用体积），提交后只重算未锁定池。 */
export default function RemeasurePanel({ experimentId, samples, onDone, showError }) {
  const [drafts, setDrafts] = useState({}) // sampleId -> {concentration, available_volume}
  const [submitting, setSubmitting] = useState(false)

  const setField = (sid, key, value) => {
    setDrafts((d) => ({
      ...d,
      [sid]: { concentration: '', available_volume: '', ...d[sid], [key]: value },
    }))
  }

  const pending = Object.entries(drafts).filter(
    ([, v]) => v.concentration !== '' && Number(v.concentration) > 0
  )

  const submit = async () => {
    const bad = pending.find(
      ([, v]) =>
        !(Number(v.concentration) > 0) ||
        (v.available_volume !== '' && !(Number(v.available_volume) > 0))
    )
    if (bad) {
      showError('复测浓度（及可选的可用体积）必须为正数')
      return
    }
    setSubmitting(true)
    try {
      const updated = await api.remeasure(
        experimentId,
        pending.map(([sid, v]) => {
          const item = { sample_id: Number(sid), concentration: String(v.concentration) }
          if (v.available_volume !== '')
            item.available_volume = String(v.available_volume)
          return item
        })
      )
      onDone(updated)
      setDrafts({})
    } catch (e) {
      showError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="side-panel">
      <p className="muted">
        录入复测浓度后提交：<b>未锁定池</b>按新浓度重算；<b>锁定池</b>保留原配方，
        仅在配液表上显示受影响警示并写入版本记录。
      </p>
      <div className="table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>样本</th>
              <th>原浓度</th>
              <th>新浓度</th>
              <th>新可用体积(可选)</th>
            </tr>
          </thead>
          <tbody>
            {samples.map((s) => (
              <tr key={s.id}>
                <td>{s.code}</td>
                <td className="mono">{s.concentration}</td>
                <td>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    placeholder="新浓度"
                    value={drafts[s.id]?.concentration ?? ''}
                    onChange={(e) => setField(s.id, 'concentration', e.target.value)}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    placeholder="选填"
                    value={drafts[s.id]?.available_volume ?? ''}
                    onChange={(e) => setField(s.id, 'available_volume', e.target.value)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button
        className="btn primary"
        disabled={submitting || pending.length === 0}
        onClick={submit}
      >
        {submitting
          ? '重算中…'
          : `提交复测并重算（${pending.length} 个样本）`}
      </button>
    </div>
  )
}
