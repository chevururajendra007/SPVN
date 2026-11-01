import { useEffect, useRef, useState } from 'react'

const SUGGESTIONS = ["Today's Word of the Day", 'How do admissions work?', 'Quiz me on Tolerance', 'స్కూల్ ఎక్కడ ఉంది?']
const API = import.meta.env.VITE_API_URL || ''

export default function App() {
  const [history, setHistory] = useState([
    { role: 'assistant', content: 'Namaste! I am Ask SPV. Ask me about admissions, the school, or our Word of the Day.' },
  ])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef(null)
  useEffect(() => end.current?.scrollIntoView({ behavior: 'smooth' }), [history, busy])

  async function send(text) {
    const message = (text ?? input).trim()
    if (!message || busy) return
    setInput('')
    const past = history.slice(1) // drop the greeting
    setHistory(h => [...h, { role: 'user', content: message }])
    setBusy(true)
    try {
      const r = await fetch(`${API}/api/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, history: past }),
      })
      if (!r.ok) throw new Error(r.status)
      const { reply } = await r.json()
      setHistory(h => [...h, { role: 'assistant', content: reply }])
    } catch {
      setHistory(h => [...h, { role: 'assistant', content: 'Sorry, I could not connect. Please try again.' }])
    } finally { setBusy(false) }
  }

  return (
    <div className="shell">
      <header>
        <img src="/logo.png" alt="" />
        <div><b>Ask SPV</b><span>Sri Pragathi Vidyaniketan · AI assistant</span></div>
      </header>
      <main>
        {history.map((m, i) => <div key={i} className={`msg ${m.role}`}>{m.content}</div>)}
        {busy && <div className="msg assistant typing"><i /><i /><i /></div>}
        <div ref={end} />
      </main>
      <div className="chips">{SUGGESTIONS.map(s => <button key={s} onClick={() => send(s)}>{s}</button>)}</div>
      <form onSubmit={e => { e.preventDefault(); send() }}>
        <input value={input} onChange={e => setInput(e.target.value)} placeholder="Type in English or తెలుగు…" />
        <button disabled={busy || !input.trim()}>Send</button>
      </form>
    </div>
  )
}
