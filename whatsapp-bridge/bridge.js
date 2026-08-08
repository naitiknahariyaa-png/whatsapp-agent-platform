require('dotenv').config();
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcodeTerminal = require('qrcode-terminal');
const QRCode = require('qrcode');
const express = require('express');
const { WebSocketServer } = require('ws');
const axios = require('axios');
const fs = require('fs');
const path = require('path');

// ============ ANTI-BAN LAYER ============
const ANTI_BAN = {
  enabled: true,
  minDelayMs: 3000,
  maxDelayMs: 8000,
  maxMessagesPerMin: 8,
  maxMessagesPerHour: 120,
  maxNewChatsPerDay: 20,
  humanTypingDelay: true,
  quietHours: { enabled: true, start: 22, end: 8 },
  messageCount: { minute: 0, hour: 0, day: 0, lastMinute: Date.now(), lastHour: Date.now(), lastDay: Date.now() },
  newChatsToday: 0,
  lastNewChatDay: new Date().getDate(),
};

function antiBanDelay() {
  return new Promise(resolve => {
    const delay = Math.floor(Math.random() * (ANTI_BAN.maxDelayMs - ANTI_BAN.minDelayMs)) + ANTI_BAN.minDelayMs;
    setTimeout(resolve, delay);
  });
}

function antiBanCheck() {
  const now = Date.now();
  if (now - ANTI_BAN.messageCount.lastMinute > 60000) { ANTI_BAN.messageCount.minute = 0; ANTI_BAN.messageCount.lastMinute = now; }
  if (now - ANTI_BAN.messageCount.lastHour > 3600000) { ANTI_BAN.messageCount.hour = 0; ANTI_BAN.messageCount.lastHour = now; }
  if (now - ANTI_BAN.messageCount.lastDay > 86400000) { ANTI_BAN.messageCount.day = 0; ANTI_BAN.messageCount.lastDay = now; }
  if (new Date().getDate() !== ANTI_BAN.lastNewChatDay) { ANTI_BAN.newChatsToday = 0; ANTI_BAN.lastNewChatDay = new Date().getDate(); }
  const hour = new Date().getHours();
  if (ANTI_BAN.quietHours.enabled && hour >= ANTI_BAN.quietHours.start && hour < ANTI_BAN.quietHours.end) {
    return { allowed: false, reason: 'Quiet hours (10pm-8am)' };
  }
  if (ANTI_BAN.messageCount.minute >= ANTI_BAN.maxMessagesPerMin) return { allowed: false, reason: 'Rate limit: too many messages per minute' };
  if (ANTI_BAN.messageCount.hour >= ANTI_BAN.maxMessagesPerHour) return { allowed: false, reason: 'Rate limit: too many messages per hour' };
  if (ANTI_BAN.newChatsToday >= ANTI_BAN.maxNewChatsPerDay) return { allowed: false, reason: 'New chat limit reached for today' };
  return { allowed: true };
}

function antiBanTrack(isNewChat) {
  ANTI_BAN.messageCount.minute++;
  ANTI_BAN.messageCount.hour++;
  ANTI_BAN.messageCount.day++;
  if (isNewChat) ANTI_BAN.newChatsToday++;
}

function humanTypingDelay(text) {
  return new Promise(resolve => {
    if (!ANTI_BAN.humanTypingDelay) { resolve(); return; }
    const charsPerSec = Math.floor(Math.random() * 20) + 15;
    const delay = Math.min(Math.max((text || 'Hello').length / charsPerSec * 1000, 1000), 5000);
    setTimeout(resolve, delay);
  });
}
// ============ END ANTI-BAN LAYER ============

const AGENT_API_URL = process.env.AGENT_API_URL || 'http://localhost:8000';
const WS_PORT = process.env.WS_PORT || 3002;
const HTTP_PORT = process.env.HTTP_PORT || 3001;
const AUTH_PATH = path.join(__dirname, '.wwebjs_auth');
const QR_FILE_PATH = path.join(__dirname, 'qr.png');
const BRIDGE_SECRET = process.env.WA_BRIDGE_SECRET || 'your_bridge_secret_here';
const MAX_MEMORY_MB = parseInt(process.env.MAX_MEMORY_MB || '256', 10);

function clearAuthSession() {
    try {
        if (fs.existsSync(AUTH_PATH)) {
            fs.rmSync(AUTH_PATH, { recursive: true, force: true });
        }
    } catch (e) { console.error('[!] Clear session failed:', e.message); }
}

const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        headless: 'new',
        executablePath: process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--single-process',
            '--no-zygote',
            '--disable-extensions',
            '--disable-background-networking',
            '--disable-default-apps',
            '--disable-sync',
            '--disable-translate',
            '--js-flags=--max-old-space-size=128'
        ]
    }
});

// ============ MEMORY OPTIMIZATION ============
// Periodically check memory and log usage
const memoryTimer = setInterval(() => {
    try {
        const usedMB = process.memoryUsage().heapUsed / 1024 / 1024;
        if (usedMB > MAX_MEMORY_MB) {
            console.log(`[i] Memory high: ${usedMB.toFixed(0)}MB. Cleaning up...`);
        }
    } catch (e) {}
}, 60000);
memoryTimer.unref();

// Clean up old QR file on startup
try { if (fs.existsSync(QR_FILE_PATH)) fs.unlinkSync(QR_FILE_PATH); } catch(e) {}
// ============ END MEMORY OPTIMIZATION ============

// Store latest QR globally for API
let latestQR = null;

// QR handler - save QR for API
client.on('qr', async (qr) => {
    latestQR = qr;
    console.log('\n=== SCAN THIS QR CODE WITH WHATSAPP ===');
    qrcodeTerminal.generate(qr, { small: true });
    console.log('===========================================\n');
    try {
        await QRCode.toFile(QR_FILE_PATH, qr);
        console.log(`[✓] QR code saved to: ${QR_FILE_PATH}`);
    } catch (err) {
        console.error('[!] Failed to save qr.png:', err.message);
    }
});

client.on('authenticated', () => {
    console.log('[✓] WhatsApp authenticated');
    latestQR = null; // clear stored QR after successful auth
    try { if (fs.existsSync(QR_FILE_PATH)) fs.unlinkSync(QR_FILE_PATH); } catch (e) {}
});

client.on('auth_failure', (msg) => {
    console.error('[✗] Auth failure:', msg);
    clearAuthSession();
});

client.on('ready', () => {
    console.log('✅ WhatsApp connected! Anti-ban layer active');
    global.WA_CONNECTED = true;
});

client.on('message', async (message) => {
    if (message.from.includes('status') || message.from === 'me' || message.isGroup) return;
    console.log(`[IN] ${message.from}: ${message.body.substring(0, 80)}`);

    try {
        const payload = JSON.stringify({
            from: message.from.replace('@c.us', ''),
            to: message.to.replace('@c.us', ''),
            body: message.body
        });
        const signature = require('crypto').createHmac('sha256', BRIDGE_SECRET).update(payload).digest('hex');
        const resp = await axios.post(`${AGENT_API_URL}/webhook`, JSON.parse(payload), {
            timeout: 30000,
            headers: { 'X-Bridge-Signature': signature, 'Content-Type': 'application/json' }
        });
        if (resp.data.reply) {
            await client.sendPresenceAvailable();
            await new Promise(r => setTimeout(r, Math.floor(Math.random() * 4000) + 3000));
            await safeSend(message.from, resp.data.reply);
            console.log(`[OUT] ${message.from}: ${resp.data.reply.substring(0, 50)}...`);
        }
    } catch (err) {
        if (err.code !== 'ECONNREFUSED') console.error(`[✗] Error: ${err.message}`);
    }
});

async function safeSend(phone, message) {
    const banCheck = antiBanCheck();
    if (!banCheck.allowed) {
        console.log('[!] Anti-ban:', banCheck.reason);
        return { success: false, error: banCheck.reason };
    }
    await antiBanDelay();
    await humanTypingDelay(message);
    antiBanTrack(false);

    try {
        const chatId = phone.includes('@c.us') ? phone : `${phone}@c.us`;
        const r = await client.sendMessage(chatId, message);
        return { success: true, messageId: r.id._serialized };
    } catch (e) {
        console.error('[✗] Send failed:', e.message);
        return { success: false, error: e.message };
    }
}

const app = express();
app.use(express.json({ limit: '10mb' }));
app.use('/static', express.static(__dirname));

app.post('/send', async (req, res) => {
    const { phone, message } = req.body;
    if (!phone || !message) return res.status(400).json({ error: 'phone and message required' });
    try {
        const result = await safeSend(phone, message);
        if (!result.success) return res.status(429).json({ error: result.error });
        res.json({ success: true, messageId: result.messageId });
    } catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/send-media', async (req, res) => {
    const { phone, base64, mimetype, caption, filename } = req.body;
    if (!phone || !base64) return res.status(400).json({ error: 'phone and base64 required' });
    try {
        const chatId = phone.includes('@c.us') ? phone : `${phone}@c.us`;
        const media = new MessageMedia(mimetype || 'image/png', base64, filename || 'file');
        const result = await safeSend(phone, caption || '');
        if (!result.success) return res.status(429).json({ error: result.error });
        await client.sendMessage(chatId, media);
        res.json({ success: true, messageId: result.messageId });
    } catch (e) { res.status(500).json({ error: e.message }); }
});

app.get('/health', (req, res) => {
    const usedMB = process.memoryUsage().heapUsed / 1024 / 1024;
    res.json({
        status: 'ok',
        whatsapp: client.info ? { number: client.info.wid.user, name: client.info.pushname } : 'disconnected',
        memory_mb: Math.round(usedMB)
    });
});

app.get('/qr', (req, res) => {
    if (latestQR) {
        QRCode.toDataURL(latestQR).then(url => {
            res.json({ qr: latestQR, data_url: url, status: 'ready' });
        }).catch(() => {
            res.json({ qr: latestQR, data_url: null, status: 'ready' });
        });
    } else {
        if (fs.existsSync(QR_FILE_PATH)) {
            res.sendFile(QR_FILE_PATH);
        } else {
            res.json({ qr: null, data_url: null, status: 'waiting' });
        }
    }
});

const wss = new WebSocketServer({ port: WS_PORT });
wss.on('connection', (ws) => {
    ws.send(JSON.stringify({ type: 'connected', message: 'WhatsApp Bridge Connected' }));
    if (latestQR) {
        ws.send(JSON.stringify({ type: 'qr', data: latestQR }));
    }
});

app.listen(HTTP_PORT, () => console.log(`[ℹ] Bridge HTTP on :${HTTP_PORT}, WS on :${WS_PORT}`));
client.initialize().catch(err => { console.error('[✗] Init failed:', err); process.exit(1); });