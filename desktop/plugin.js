// undo-send Desktop chip: a live countdown in the status bar with Undo and
// Send now. Talks to dashboard/plugin_api.py, which shares the SQLite store
// with the agent's middleware, so a tap here cancels the held action.
import { host, STATUSBAR_AREAS } from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

let rest = null

async function call(path, method) {
  const opts = method ? { method } : undefined
  try {
    return await rest(path, opts)
  } catch (e) {
    // Some builds want the path without a leading slash.
    return await rest(path.replace(/^\//, ''), opts)
  }
}

const btn = (bg) => ({
  border: 'none', borderRadius: 4, padding: '1px 8px', marginLeft: 6,
  fontSize: 11, fontWeight: 600, cursor: 'pointer', background: bg, color: '#fff'
})

function Chip() {
  const [items, setItems] = useState([])
  const [flash, setFlash] = useState('')
  const [err, setErr] = useState('')
  const known = useRef(new Set())
  const failingSince = useRef(0)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const d = await call('/pending')
        if (!alive) return
        failingSince.current = 0
        setErr('')
        const list = (d && d.items) || []
        for (const it of list) {
          if (!known.current.has(it.id)) {
            known.current.add(it.id)
            host.notify({ kind: 'info', title: 'Waiting to send', message: it.summary })
          }
        }
        setItems(list)
      } catch (e) {
        if (!alive) return
        if (!failingSince.current) failingSince.current = Date.now()
        // Restarts take a while; only show an error if it lasts over 90s.
        const long = Date.now() - failingSince.current > 90000
        setErr(long ? String((e && e.message) || e).slice(0, 120) : 'reconnecting')
      }
    }
    tick()
    const t = setInterval(tick, 500)
    return () => { alive = false; clearInterval(t) }
  }, [])

  const show = (msg) => { setFlash(msg); setTimeout(() => setFlash(''), 3500) }

  if (!items.length) {
    if (flash) return jsx('span', { style: { fontSize: 12, opacity: 0.85 }, children: flash })
    // Small idle badge so you can see Undo Send is armed (or why it isn't).
    const quiet = !err || err === 'reconnecting'
    return jsx('span', {
      title: !err ? 'Undo Send is on. Outgoing actions wait here before they run.'
        : quiet ? 'Waiting for the Hermes backend to come back.'
        : `Undo Send can't reach its backend: ${err}`,
      style: { fontSize: 12, opacity: quiet ? 0.6 : 1, color: quiet ? undefined : '#f87171' },
      children: !err ? '↩ Undo Send' : quiet ? '↩ Undo Send · reconnecting…' : `↩ Undo Send: ${err}`
    })
  }

  const it = items[items.length - 1]
  const left = Math.ceil(it.seconds_left)
  const more = items.length > 1 ? ` (+${items.length - 1})` : ''
  const text = it.summary.length > 48 ? it.summary.slice(0, 45) + '…' : it.summary

  return jsxs('span', {
    title: items.map((x) => `${Math.ceil(x.seconds_left)}s  ${x.summary}`).join('\n'),
    style: { display: 'inline-flex', alignItems: 'center', fontSize: 12, gap: 4 },
    children: [
      jsx('span', { style: { color: '#f59e0b', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }, children: `⏳ ${left}s` }),
      jsx('span', { style: { opacity: 0.9 }, children: text + more }),
      jsx('button', {
        type: 'button', style: btn('#dc2626'),
        onClick: async () => {
          const r = await call(`/unsend/${it.id}`, 'POST')
          show(r && r.ok ? '↩ Undone. It never ran.' : 'Too late, it already ran.')
        },
        children: 'Undo'
      }),
      jsx('button', {
        type: 'button', style: btn('#52525b'),
        onClick: async () => { await call(`/sendnow/${it.id}`, 'POST'); show('Sending now') },
        children: 'Send now'
      })
    ]
  })
}

export default {
  id: 'undo-send',
  name: 'Undo Send',
  defaultEnabled: true,
  register(ctx) {
    rest = ctx.rest
    ctx.register({
      id: 'countdown',
      area: STATUSBAR_AREAS.right,
      order: 5,
      render: () => jsx(Chip, {})
    })
  }
}
