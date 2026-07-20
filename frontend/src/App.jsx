import { useState, useRef } from 'react'
import './App.css'

const API_BASE = import.meta.env.PROD ? '/api' : 'http://localhost:8000'

function App() {
  const [question, setQuestion] = useState('')
  const [steps, setSteps] = useState([])
  const [answer, setAnswer] = useState('')
  const [loading, setLoading] = useState(false)

  const runQuery = async () => {
    if (!question.trim() || loading) return
    setSteps([])
    setAnswer('')
    setLoading(true)

    try {
      const response = await fetch(`${API_BASE}/ask-stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n\n')
        buffer = lines.pop()

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const event = JSON.parse(line.slice(6))
          if (event.type === 'status') {
            setSteps((prev) => [...prev, event.text])
          } else if (event.type === 'final') {
            setAnswer(event.text)
          }
        }
      }
    } catch (err) {
      setAnswer(`Error: ${err.message}. Is the backend running on ${API_BASE}?`)
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      runQuery()
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>🛠️ Infra Ops Assistant</h1>
        <p className="subtitle">
          Ask about your Terraform config, cluster health, or CI/CD status.
        </p>
      </header>

      <div className="input-row">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="e.g. Is my cluster healthy and did my last CI run pass?"
          rows={2}
        />
        <button onClick={runQuery} disabled={loading}>
          {loading ? 'Running...' : 'Ask'}
        </button>
      </div>

      {steps.length > 0 && (
        <div className="steps-panel">
          <h3>Agent Activity</h3>
          <ul>
            {steps.map((s, i) => (
              <li key={i} className="step-item">
                <span className="step-dot" />
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}

      {answer && (
        <div className="answer-panel">
          <h3>Result</h3>
          <div className="answer-text">{answer}</div>
        </div>
      )}
    </div>
  )
}

export default App
