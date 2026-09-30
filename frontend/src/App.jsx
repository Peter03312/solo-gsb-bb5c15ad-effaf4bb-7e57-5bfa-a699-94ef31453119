import React, { useEffect, useState, useCallback } from 'react'
import { api } from './api.js'
import ExperimentList from './views/ExperimentList.jsx'
import ExperimentDetail from './views/ExperimentDetail.jsx'
import CreateExperiment from './views/CreateExperiment.jsx'

export default function App() {
  const [view, setView] = useState({ name: 'list' })
  const [error, setError] = useState('')

  const showError = useCallback((msg) => {
    setError(msg)
    window.setTimeout(() => setError(''), 6000)
  }, [])

  let content
  if (view.name === 'list') {
    content = (
      <ExperimentList
        onOpen={(id) => setView({ name: 'detail', id })}
        onCreate={() => setView({ name: 'create' })}
        showError={showError}
      />
    )
  } else if (view.name === 'create') {
    content = (
      <CreateExperiment
        onCancel={() => setView({ name: 'list' })}
        onCreated={(id) => setView({ name: 'detail', id })}
        showError={showError}
      />
    )
  } else {
    content = (
      <ExperimentDetail
        id={view.id}
        onBack={() => setView({ name: 'list' })}
        showError={showError}
      />
    )
  }

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand" onClick={() => setView({ name: 'list' })}>
          🧬 测序样本拼池工作台
        </button>
        <span className="subtitle">
          投料量 ÷ 浓度 = 取液量 ｜ 同池索引不重复 ｜ 样本数优先、池数最少
        </span>
      </header>
      {error && (
        <div className="toast error" role="alert">
          ⚠️ {error}
        </div>
      )}
      <main className="container">{content}</main>
      <footer className="footer">
        所有数量计算在服务端以定点小数完成；不满足约束的样本不会进入任何配方。
      </footer>
    </div>
  )
}
