import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function ExperimentList({ onOpen, onCreate, showError }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    try {
      setItems(await api.listExperiments())
    } catch (e) {
      showError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const remove = async (id, name) => {
    if (!window.confirm(`确定删除计划「${name}」吗？此操作不可恢复。`)) return
    try {
      await api.deleteExperiment(id)
      load()
    } catch (e) {
      showError(e.message)
    }
  }

  return (
    <section>
      <div className="section-head">
        <h2>拼池计划</h2>
        <button className="btn primary" onClick={onCreate}>
          + 新建计划
        </button>
      </div>
      {loading ? (
        <p>加载中…</p>
      ) : items.length === 0 ? (
        <div className="empty">
          还没有拼池计划。点击「新建计划」录入样本与约束，系统会自动给出最优配液方案。
        </div>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>名称</th>
              <th>可用池数</th>
              <th>已安排 / 总样本</th>
              <th>已用池</th>
              <th>当前版本</th>
              <th>创建时间 (UTC)</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((e) => (
              <tr key={e.id}>
                <td>{e.id}</td>
                <td className="link" onClick={() => onOpen(e.id)}>
                  {e.name}
                </td>
                <td>{e.available_pools}</td>
                <td>
                  <span className={e.arranged_count === e.total_samples ? 'ok' : 'warn'}>
                    {e.arranged_count} / {e.total_samples}
                  </span>
                </td>
                <td>{e.pool_count}</td>
                <td>v{e.current_version}</td>
                <td>{new Date(e.created_at).toLocaleString()}</td>
                <td>
                  <button className="btn small" onClick={() => onOpen(e.id)}>
                    打开
                  </button>
                  <button
                    className="btn small danger"
                    onClick={() => remove(e.id, e.name)}
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
