/**
 * WhatsApp Bridge — WhatsApp Web automation via whatsapp-web.js
 * Serves QR codes, status, and message forwarding to the agent API.
 */
require('dotenv').config();
const express = require('express');
const http = require('http');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode');
const axios = require('axios');

// ── Configuration ────────────────────────────────────────────────────────────
const HTTP_PORT = parseInt(process.env.HTTP_PORT || '3001', 10);
const AGENT_API_URL = process.env.AGENT_API_URL || 'http://localhost:8000';
const WA_BRIDGE_SECRET = process.env.WA_BRIDGE_SECRET || 'wap_bridge_secret_2026';

// ── State ───────────────────────────────────────────────────────────────────
let client = null;
let isConnected = false;
let connectionState = 'disconnected';
let currentQR = null;
let currentQRDataUrl = null;
let currentQRTimestamp = null;
let refreshingQr = false;
let whatsappInfo = null;

async function forwardToAgent(event, data) {
  try {
    const body = JSON.stringify({ event, ...data });
    const signature = crypto.createHmac('sha256', WA_BRIDGE_SECRET).update(body).digest('hex');
    const resp = await axios.post(AGENT_API_URL + '/api/webhook', body, {
      headers: { 'Content-Type': 'application/json', 'X-Bridge-Signature': signature },
      timeout: 10000,
    });
    if (resp.status >= 200 && resp.status < 300) return resp.data;
  } catch (err) {
    console.error('[✗] Failed to forward event ' + event + ' to agent:', err.message);
  }
  return null;
}

function findChromePath() {
  const candidates = [
    process.env.CHROME_PATH,
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium-browser',
    '/usr/bin/chromium',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ].filter(Boolean);
  for (const c of candidates) { try { if (fs.existsSync(c)) return c; } catch (e) {} }
  return undefined;
}

function createClient() {
  const chromePath = findChromePath();
  const puppeteerOptions = {
    headless: true,
    args: [
      '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
      '--disable-gpu', '--disable-extensions', '--disable-background-networking',
      '--disable-default-apps', '--disable-sync', '--no-first-run',
      '--no-default-browser-check', '--disable-features=TranslateUI',
      '--disable-features=OptimizationHints', '--disable-features=MediaRouter',
      '--disable-features=DialMediaRouteProvider',
    ],
  };
  if (chromePath) puppeteerOptions.executablePath = chromePath;
  return new Client({
    authStrategy: new LocalAuth({ dataPath: path.join(__dirname, '.wwebjs_auth') }),
    puppeteer: puppeteerOptions,
    qrMaxRetries: 3,
    takeoverOnConflict: true,
  });
}

function initClient() {
  if (client) { try { client.destroy(); } catch (e) {} }
  client = createClient();
  client.on('qr', async (qr) => {
    currentQR = qr;
    currentQRTimestamp = Date.now();
    connectionState = 'qr';
    try { currentQRDataUrl = await qrcode.toDataURL(qr); } catch (e) { currentQRDataUrl = null; }
    console.log('📱 QR code generated. Scan with WhatsApp -> Linked Devices.');
  });
  client.on('authenticated', () => { connectionState = 'authenticated'; console.log('✅ Authenticated with WhatsApp.'); });
  client.on('auth_failure', (msg) => { connectionState = 'failed'; isConnected = false; console.error('❌ Auth failure:', msg); });
  client.on('ready', async () => {
    isConnected = true;
    connectionState = 'connected';
    try { whatsappInfo = { number: client.info.wid.user, name: client.info.pushname || '', platform: client.info.platform || '' }; }
    catch (e) { whatsappInfo = {}; }
    console.log('✅ WhatsApp connected!');
    forwardToAgent('connected', whatsappInfo || {});
  });
  client.on('message', async (msg) => {
    if (msg.fromMe) return;
    try {
      const contact = await msg.getContact();
      const result = await forwardToAgent('message', {
        from: msg.from,
        from_name: contact ? contact.pushname || contact.name || '' : '',
        body: msg.body,
        timestamp: msg.timestamp,
        hasMedia: msg.hasMedia,
      });
      if (result && result.reply) {
        const chatId = msg.from.includes('@') ? msg.from : msg.from + '@c.us';
        await client.sendMessage(chatId, result.reply);
      }
    } catch (e) { console.error('Message error:', e.message); }
  });
  client.on('disconnected', (reason) => {
    isConnected = false;
    connectionState = 'disconnected';
    currentQR = null;
    currentQRDataUrl = null;
    console.log('❌ Disconnected:', reason);
    forwardToAgent('disconnected', { reason });
  });
  client.initialize().catch((err) => {
    console.error('❌ Init failed:', err.message);
    connectionState = 'failed';
  });
}

const SEND_WINDOW_MS = 60 * 1000;
const MAX_SENDS_PER_MINUTE = 20;
const sendHistory = [];

function canSendMessage() {
  const now = Date.now();
  while (sendHistory.length && sendHistory[0] < now - SEND_WINDOW_MS) {
    sendHistory.shift();
  }
  if (sendHistory.length >= MAX_SENDS_PER_MINUTE) {
    return false;
  }
  sendHistory.push(now);
  return true;
}

async function refreshQr() {
  if (isConnected) {
    return { status: 'connected', message: 'Already connected', qr: null };
  }
  if (refreshingQr) {
    return { status: 'refreshing', message: 'QR refresh already in progress' };
  }
  refreshingQr = true;
  try {
    if (client) {
      try { await client.destroy(); } catch (e) { /* ignore */ }
      client = null;
    }
    currentQR = null;
    currentQRDataUrl = null;
    currentQRTimestamp = null;
    connectionState = 'connecting';
    isConnected = false;
    whatsappInfo = null;
    initClient();
    return { status: 'refreshing', message: 'Refreshing QR code, please wait 5-10 seconds' };
  } finally {
    refreshingQr = false;
  }
}

const app = express();
app.use(express.json({ limit: '10mb' }));
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Headers', 'Content-Type, X-Bridge-Signature');
  res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  if (req.method === 'OPTIONS') return res.sendStatus(204);
  next();
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok', connected: isConnected, connection_state: connectionState, whatsapp: whatsappInfo || {}, uptime: process.uptime() });
});

app.get('/qr', (req, res) => {
  if (currentQR && currentQRDataUrl) {
    const age = currentQRTimestamp ? Math.floor((Date.now() - currentQRTimestamp) / 1000) : null;
    return res.json({
      status: 'ready',
      qr: currentQR,
      data_url: currentQRDataUrl,
      generated_at: currentQRTimestamp,
      age_seconds: age,
      message: 'Scan the QR code with WhatsApp to connect',
    });
  }
  if (connectionState === 'connected') return res.json({ status: 'connected', qr: null, message: 'Already connected' });
  return res.json({ status: 'waiting', qr: null, message: 'Waiting for QR code...' });
});

app.post('/qr/refresh', async (req, res) => {
  const result = await refreshQr();
  res.json(result);
});

app.post('/send', async (req, res) => {
  try {
    const { to, message } = req.body || {};
    if (!to || !message) return res.status(400).json({ error: 'to and message are required' });
    if (!canSendMessage()) return res.status(429).json({ error: 'Rate limit exceeded. Try again in a few seconds.' });
    if (!isConnected || !client) return res.status(503).json({ error: 'WhatsApp not connected' });
    const chatId = to.includes('@') ? to : to + '@c.us';
    const sent = await client.sendMessage(chatId, message);
    return res.json({ status: 'sent', id: sent.id._serialized });
  } catch (e) { return res.status(500).json({ error: e.message }); }
});

app.get('/status', (req, res) => {
  res.json({ connected: isConnected, connection_state: connectionState, whatsapp: whatsappInfo || {} });
});

app.post('/connect/request-code', (req, res) => {
  res.json({ status: 'qr_required', message: 'WhatsApp Web uses QR code authentication. Scan the QR code from /qr to connect.', qr: currentQR, data_url: currentQRDataUrl });
});

app.post('/connect/verify', (req, res) => {
  res.json({ status: 'qr_required', message: 'WhatsApp Web uses QR code authentication. Scan the QR code to connect.' });
});

app.post('/broadcast', async (req, res) => {
  try {
    const { contacts, message } = req.body || {};
    if (!contacts || !Array.isArray(contacts) || !message) return res.status(400).json({ error: 'contacts (array) and message are required' });
    if (!isConnected || !client) return res.status(503).json({ error: 'WhatsApp not connected' });
    let sent = 0, failed = 0;
    for (const contact of contacts) {
      if (!canSendMessage()) {
        return res.status(429).json({ error: 'Rate limit exceeded while broadcasting. Try again later.' });
      }
      try {
        const chatId = contact.includes('@') ? contact : contact + '@c.us';
        await client.sendMessage(chatId, message);
        sent++;
        await new Promise((r) => setTimeout(r, 1000 + Math.random() * 1200));
      } catch (e) { failed++; }
    }
    return res.json({ status: 'complete', sent, failed });
  } catch (e) { return res.status(500).json({ error: e.message }); }
});

const server = http.createServer(app);
server.listen(HTTP_PORT, () => {
  console.log('[✓] WhatsApp Bridge HTTP listening on port ' + HTTP_PORT);
  console.log('[✓] Forwarding events to agent: ' + AGENT_API_URL);
  initClient();
});

process.on('SIGINT', () => {
  console.log('[!] Shutting down bridge...');
  if (client) { try { client.destroy(); } catch (e) {} }
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 3000);
});
