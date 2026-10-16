// EDITH WhatsApp Bridge (Fase 9) — Baileys v7
//
// WhatsApp <-> este proceso <-> EDITH (FastAPI en 127.0.0.1).
//  * Se vincula una sola vez escaneando un QR (terminal o interfaz de EDITH > Laptop > Canales).
//  * Solo atiende chats privados de números autorizados (lista blanca que da EDITH).
//  * Su API HTTP escucha SOLO en 127.0.0.1 y exige la clave compartida con EDITH.
//
// Recomendación: vincula un número secundario. Baileys es un cliente no oficial de WhatsApp.

import makeWASocket, {
  Browsers, DisconnectReason, downloadMediaMessage, fetchLatestBaileysVersion,
  isLidUser, isPnUser, useMultiFileAuthState,
} from '@whiskeysockets/baileys'
import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import pino from 'pino'
import QRCode from 'qrcode'
import qrcodeTerminal from 'qrcode-terminal'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..', '..')
const DATA_DIR = path.join(ROOT, 'data', 'channels', 'whatsapp')
const AUTH_DIR = path.join(DATA_DIR, 'auth')
const QR_FILE = path.join(DATA_DIR, 'qr.png')
const SECRET_FILE = path.join(ROOT, 'data', 'channels', 'bridge_secret')
const EDITH_URL = (process.env.EDITH_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
const PORT = Number(process.env.BRIDGE_PORT || 3100)
const MAX_AUDIO_BYTES = 10 * 1024 * 1024

fs.mkdirSync(DATA_DIR, { recursive: true })
const logger = pino({ level: process.env.BRIDGE_LOG_LEVEL || 'warn' })
const log = (...a) => console.log(new Date().toLocaleTimeString('es-MX', { hour12: false }), '[bridge]', ...a)

// ---------- clave compartida con EDITH ----------
function loadSecret () {
  if (process.env.EDITH_BRIDGE_SECRET) return process.env.EDITH_BRIDGE_SECRET.trim()
  try {
    const s = fs.readFileSync(SECRET_FILE, 'utf8').trim()
    if (s.length >= 32) return s
  } catch {}
  const s = crypto.randomBytes(32).toString('base64url')
  fs.mkdirSync(path.dirname(SECRET_FILE), { recursive: true })
  fs.writeFileSync(SECRET_FILE, s)
  return s
}
const SECRET = loadSecret()
const secretOk = (v) => {
  const a = Buffer.from(String(v || ''))
  const b = Buffer.from(SECRET)
  return a.length === b.length && crypto.timingSafeEqual(a, b)
}

// ---------- números ----------
const digits = (s) => String(s || '').replace(/\D/g, '')
function canonical (n) { // mismo criterio que agent/channels/security.py
  const d = digits(n)
  if (d.length === 13 && d.startsWith('521')) return '52' + d.slice(3)
  if (d.length === 13 && d.startsWith('549')) return '54' + d.slice(3)
  return d
}

let allow = { enabled: false, numbers: new Set(), fetchedAt: 0 }
async function refreshAllowlist () {
  try {
    const r = await fetch(`${EDITH_URL}/api/channels/whatsapp/allowlist`, {
      headers: { 'X-Edith-Bridge-Secret': SECRET }, signal: AbortSignal.timeout(5000),
    })
    if (r.ok) {
      const j = await r.json()
      allow = { enabled: !!j.enabled, numbers: new Set((j.numbers || []).map(canonical)), fetchedAt: Date.now() }
    }
  } catch { /* EDITH apagada: se reintenta */ }
}
const isAllowed = (n) => allow.enabled && allow.numbers.has(canonical(n))

// ---------- estado ----------
const status = { connected: false, qr_pending: false, me: null, since: null }
const lastJidFor = new Map() // número canónico -> JID real con el que escribió
const seen = new Set()
let sock = null

async function senderNumber (key) {
  const remote = key.remoteJid || ''
  let pn = isPnUser(remote) ? remote : null
  if (!pn && key.remoteJidAlt && isPnUser(key.remoteJidAlt)) pn = key.remoteJidAlt
  if (!pn && isLidUser(remote)) {
    try { pn = await sock.signalRepository?.lidMapping?.getPNForLID?.(remote) } catch {}
  }
  return pn ? pn.split('@')[0].split(':')[0] : ''
}

function unwrap (message) {
  return message?.ephemeralMessage?.message || message?.viewOnceMessageV2?.message ||
    message?.viewOnceMessage?.message || message?.documentWithCaptionMessage?.message || message
}

async function handleMessage (m) {
  if (!m.message || m.key.fromMe) return
  const remote = m.key.remoteJid || ''
  if (/@(g\.us|broadcast|newsletter)$/.test(remote) || remote === 'status@broadcast') return
  if (seen.has(m.key.id)) return
  seen.add(m.key.id)
  if (seen.size > 2000) seen.delete(seen.values().next().value)

  const number = await senderNumber(m.key)
  if (Date.now() - allow.fetchedAt > 5 * 60 * 1000) await refreshAllowlist()
  if (!isAllowed(number)) return // silencio total con desconocidos
  lastJidFor.set(canonical(number), remote)

  const msg = unwrap(m.message)
  const text = msg?.conversation || msg?.extendedTextMessage?.text || msg?.imageMessage?.caption || ''
  const payload = { from: number, message_id: m.key.id, push_name: m.pushName || '', text }

  if (msg?.audioMessage) {
    if (Number(msg.audioMessage.fileLength || 0) > MAX_AUDIO_BYTES) {
      await sock.sendMessage(remote, { text: 'Esa nota de voz es muy larga para mí. ¿Me mandas una más corta?' })
      return
    }
    await sock.sendPresenceUpdate('recording', remote).catch(() => {})
    const buf = await downloadMediaMessage(m, 'buffer', {}, { logger, reuploadRequest: sock.updateMediaMessage })
    payload.audio_b64 = Buffer.from(buf).toString('base64')
    payload.audio_mime = msg.audioMessage.mimetype || 'audio/ogg'
  } else if (!text) {
    await sock.sendMessage(remote, { text: 'Por ahora solo entiendo texto y notas de voz 🙂' })
    return
  }

  await sock.readMessages([m.key]).catch(() => {})
  await sock.sendPresenceUpdate('composing', remote).catch(() => {})
  let reply
  try {
    const r = await fetch(`${EDITH_URL}/api/channels/whatsapp/inbound`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Edith-Bridge-Secret': SECRET },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(240000),
    })
    reply = r.ok ? await r.json() : { reply_text: `⚠️ EDITH respondió con un error (HTTP ${r.status}).` }
  } catch (e) {
    reply = { reply_text: '⚠️ No pude contactar a EDITH en la computadora. ¿Está encendida?' }
  } finally {
    await sock.sendPresenceUpdate('paused', remote).catch(() => {})
  }
  if (!reply || reply.ignore) return
  if (reply.reply_audio_b64) {
    await sock.sendMessage(remote, {
      audio: Buffer.from(reply.reply_audio_b64, 'base64'), mimetype: 'audio/ogg; codecs=opus', ptt: true,
    })
  }
  if (reply.reply_text) {
    const prefix = reply.transcript ? `🎙️ _${reply.transcript}_\n\n` : ''
    await sock.sendMessage(remote, { text: prefix + reply.reply_text })
  }
}

// ---------- conexión a WhatsApp ----------
async function start () {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR)
  const latest = await fetchLatestBaileysVersion().catch(() => null)
  sock = makeWASocket({
    auth: state, logger, version: latest?.version,
    browser: Browsers.windows('EDITH'), markOnlineOnConnect: false, syncFullHistory: false,
  })
  sock.ev.on('creds.update', saveCreds)
  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      status.qr_pending = true
      qrcodeTerminal.generate(qr, { small: true })
      await QRCode.toFile(QR_FILE, qr, { width: 320, margin: 2 }).catch(() => {})
      log('Escanea el QR: WhatsApp > Dispositivos vinculados > Vincular dispositivo')
    }
    if (connection === 'open') {
      Object.assign(status, { connected: true, qr_pending: false, me: sock.user?.id?.split(':')[0] || null, since: new Date().toISOString() })
      fs.rmSync(QR_FILE, { force: true })
      log('Conectado a WhatsApp como', status.me)
      refreshAllowlist()
    }
    if (connection === 'close') {
      status.connected = false
      const code = lastDisconnect?.error?.output?.statusCode
      if (code === DisconnectReason.loggedOut) {
        log('La sesión se cerró desde el teléfono. Hay que volver a vincular.')
        fs.rmSync(AUTH_DIR, { recursive: true, force: true })
      } else {
        log('Conexión cerrada (código', code, '), reintentando…')
      }
      setTimeout(start, 3000)
    }
  })
  sock.ev.on('messages.upsert', ({ messages, type }) => {
    if (type !== 'notify') return
    for (const m of messages) handleMessage(m).catch((e) => log('error procesando mensaje:', e?.message))
  })
}

// ---------- API local para EDITH (solo 127.0.0.1) ----------
async function jidFor (number) {
  const c = canonical(number)
  if (lastJidFor.has(c)) return lastJidFor.get(c)
  for (const candidate of [c, c.startsWith('52') && c.length === 12 ? '521' + c.slice(2) : null].filter(Boolean)) {
    const [res] = await sock.onWhatsApp(candidate).catch(() => [])
    if (res?.exists) return res.jid
  }
  return null
}

function readBody (req, limit = 15 * 1024 * 1024) {
  return new Promise((resolve, reject) => {
    let size = 0
    const chunks = []
    req.on('data', (c) => { size += c.length; if (size > limit) { reject(new Error('demasiado grande')); req.destroy() } else chunks.push(c) })
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
    req.on('error', reject)
  })
}

const server = http.createServer(async (req, res) => {
  const send = (code, obj) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(obj)) }
  if (!secretOk(req.headers['x-edith-bridge-secret'])) return send(401, { error: 'unauthorized' })
  try {
    if (req.method === 'GET' && req.url === '/status') return send(200, { ...status, allowlist_size: allow.numbers.size })
    if (req.method === 'POST' && req.url === '/send') {
      const { to, text, audio_b64 } = JSON.parse(await readBody(req))
      await refreshAllowlist()
      if (!isAllowed(to)) return send(403, { error: 'número no autorizado' })
      if (!status.connected) return send(503, { error: 'WhatsApp no conectado' })
      const jid = await jidFor(to)
      if (!jid) return send(404, { error: 'ese número no tiene WhatsApp' })
      if (audio_b64) await sock.sendMessage(jid, { audio: Buffer.from(audio_b64, 'base64'), mimetype: 'audio/ogg; codecs=opus', ptt: true })
      if (text) await sock.sendMessage(jid, { text })
      return send(200, { ok: true })
    }
    return send(404, { error: 'not found' })
  } catch (e) {
    return send(500, { error: e?.message || 'error' })
  }
})

server.on('error', (e) => {
  if (e.code === 'EADDRINUSE') log(`El puerto ${PORT} ya está en uso: probablemente ya hay un bridge corriendo.`)
  else log('Error del servidor local:', e.message)
  process.exit(1)
})
server.listen(PORT, '127.0.0.1', () => log(`API local en http://127.0.0.1:${PORT} · EDITH en ${EDITH_URL}`))
await refreshAllowlist()
if (!allow.enabled) log('Aviso: EDITH no respondió o WHATSAPP_ENABLED=false / sin números autorizados. Se reintentará.')
start().catch((e) => { log('No se pudo iniciar:', e?.message); process.exit(1) })
