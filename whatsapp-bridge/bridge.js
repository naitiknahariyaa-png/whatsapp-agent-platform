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
// Protects your WhatsApp account from being banned
const ANTI_BAN = {
  enabled: true,
  minDelayMs: 3000,      // Minimum delay between messages (3s)
  maxDelayMs: 8000,      // Maximum delay between messages (8s)
  maxMessagesPerMin: 8,  // Max messages per minute
  maxMessagesPerHour: 120, // Max messages per hour
  maxNewChatsPerDay: 20, // Max new chats per day
  humanTypingDelay: true, // Simulate human typing
  randomReadDelay: true,  // Random read receipts delay
  quietHours: { enabled: true, start: 22, end: 8 }, // Quiet hours 10pm-8am
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
  // Reset counters
  if (now - ANTI_BAN.messageCount.lastMinute > 60000) { ANTI_BAN.messageCount.minute = 0; ANTI_BAN.messageCount.lastMinute = now; }
  if (now - ANTI_BAN.messageCount.lastHour > 3600000) { ANTI_BAN.messageCount.hour = 0; ANTI_BAN.messageCount.lastHour = now; }
  if (now - ANTI_BAN.messageCount.lastDay > 86400000) { ANTI_BAN.messageCount.day = 0; ANTI_BAN.messageCount.lastDay = now; }
  if (new Date().getDate() !== ANTI_BAN.lastNewChatDay) { ANTI_BAN.newChatsToday = 0; ANTI_BAN.lastNewChatDay = new Date().getDate(); }

  // Check quiet hours
  const hour = new Date().getHours();
  if (ANTI_BAN.quietHours.enabled && hour >= ANTI_BAN.quietHours.start && hour < ANTI_BAN.quietHours.end) {
    return { allowed: false, reason: 'Quiet hours (10pm-8am) - message queued for morning' };
  }

  // Check rate limits
  if (ANTI_BAN.messageCount.minute >= ANTI_BAN.maxMessagesPerMin) {
    return { allowed: false, reason: 'Rate limit: too many messages per minute' };
  }
  if (ANTI_BAN.messageCount.hour >= ANTI_BAN.maxMessagesPerHour) {
    return { allowed: false, reason: 'Rate limit: too many messages per hour' };
  }
  if (ANTI_BAN.messageCount.day >= ANTI_BAN.maxMessagesPerHour * 8) {
    return { allowed: false, reason: 'Daily message limit reached' };
  }
  if (ANTI_BAN.newChatsToday >= ANTI_BAN.maxNewChatsPerDay) {
    return { allowed: false, reason: 'New chat limit reached for today' };
  }
  return { allowed: true };
}

function antiBanTrack(isNewChat) {
  ANTI_BAN.messageCount.minute++;
  ANTI_BAN.messageCount.hour++;
  ANTI_BAN.messageCount.day++;
  if (isNewChat) ANTI_BAN.newChatsToday++;
}

// Simulate human typing delay
function humanTypingDelay(text) {
  return new Promise(resolve => {
    if (!ANTI_BAN.humanTypingDelay) { resolve(); return; }
    const charsPerSec = Math.floor(Math.random() * 20) + 15; // 15-35 chars/sec
    const delay = Math.min(Math.max(text.length / charsPerSec * 1000, 1000), 5000);
    setTimeout(resolve, delay);
  });
}

// ============ END ANTI-BAN LAYER ============


const AGENT_API_URL = process.env.AGENT_API_URL || 'http://localhost:8000';
const WS_PORT = process.env.WS_PORT || 3002;
const HTTP_PORT = process.env.HTTP_PORT || 3001;

const AUTH_PATH = path.join(__dirname, '.wwebjs_auth');
const QR_FILE_PATH = path.join(__dirname, 'qr.png');

function clearAuthSession() {
    try {
        if (fs.existsSync(AUTH_PATH)) {
            console.log('[ℹ] Clearing WhatsApp session cache...');
            fs.rmSync(AUTH_PATH, { recursive: true, force: true });
            console.log('[✓] Session cache cleared.');
        }
    } catch (e) {
        console.error('[!] Failed to clear session cache:', e.message);
    }
}

// ============================================================
// ANTI-BAN SAFETY LAYER
// Protects the WhatsApp number from being flagged/banned
// ============================================================
const SAFETY = {
    minDelayMs: 8000,            // 8 sec min between messages
    maxDelayMs: 15000,           // 15 sec max (random jitter)
    typingDelayMs: [3000, 7000], // typing indicator before reply
    maxPerHour: 50,              // hard cap per hour
    maxPerDay: 500,              // hard cap per day
    broadcastDrip: {
        batchSize: 5,            // 5 msgs per batch
        pauseMs: 1800000         // 30 min pause between batches
    }
};

// Message counters (in-memory, resets on restart)
let msgCountHour = 0;
let msgCountDay = 0;
let hourStart = Date.now();
let dayStart = Date.now();

function randomDelay(min, max) {
    return new Promise(resolve => setTimeout(resolve, Math.floor(Math.random() * (max - min + 1)) + min));
}

function checkRateLimit() {
    const now = Date.now();
    if (now - hourStart > 3600000) { msgCountHour = 0; hourStart = now; }
    if (now - dayStart > 86400000) { msgCountDay = 0; dayStart = now; }
    if (msgCountHour >= SAFETY.maxPerHour) {
        console.log(`[!] Hourly limit reached (${msgCountHour}/${SAFETY.maxPerHour}). Waiting 1 hour...`);
        return false;
    }
    if (msgCountDay >= SAFETY.maxPerDay) {
        console.log(`[!] Daily limit reached (${msgCountDay}/${SAFETY.maxPerDay}). Stopping for today.`);
        return false;
    }
    return true;
}

async function safeSend(phone, message) {
    if (!checkRateLimit()) return { success: false, error: 'rate_limit' };
    // Human-like pause before sending
    await randomDelay(SAFETY.minDelayMs, SAFETY.maxDelayMs);
    const chatId = phone.includes('@c.us') ? phone : `${phone}@c.us`;
    const r = await // Anti-ban check before sending
  const banCheck = antiBanCheck();
  if (!banCheck.allowed) { console.log('⚠️ Anti-ban:', banCheck.reason); return; }
  await antiBanDelay();
  await humanTypingDelay(text || 'Hello');
  antiBanTrack(false);
  // Anti-ban check before sending
  const banCheck = antiBanCheck();
  if (!banCheck.allowed) { console.log('⚠️ Anti-ban:', banCheck.reason); return; }
  await antiBanDelay();
  await humanTypingDelay(text || 'Hello');
  antiBanTrack(false);
  client.sendMessage(chatId, message);
    msgCountHour++;
    msgCountDay++;
    return { success: true, messageId: r.id._serialized };
}

const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        headless: true,
        executablePath: process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
        args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
    }
});

const app = express();
app.use(express.json({ limit: '50mb' }));

client.on('qr', (qr) => {
    console.log('📱 QR Code generated - scan with WhatsApp');
    // Store QR for API to serve
    global.LAST_QR = qr;
    if (global.io) global.io.emit('qr', qr);
  });
  client.on('qr', (qr) => {
    console.log('📱 QR Code generated - scan with WhatsApp');
    // Store QR for API to serve
    global.LAST_QR = qr;
    if (global.io) global.io.emit('qr', qr);
  });
  client.on('qr', (qr) => {
    console.log('📱 QR Code generated - scan with WhatsApp');
    // Store QR for API to serve
    global.LAST_QR = qr;
    if (global.io) global.io.emit('qr', qr);
  });
  client.on('qr', async (qr) => {
    console.log('\n=== SCAN THIS QR CODE WITH WHATSAPP ===');
    qrcodeTerminal.generate(qr, { small: true });
    console.log('===========================================\n');
    
    try {
        await QRCode.toFile(QR_FILE_PATH, qr);
        console.log(`[✓] Clean QR code saved as image to: ${QR_FILE_PATH}`);
        console.log('[ℹ] Open this image file to scan if the terminal version looks distorted.');
    } catch (err) {
        console.error('[!] Failed to generate qr.png:', err.message);
    }
});

client.on('authenticated', () => {
    console.log('[✓] WhatsApp authenticated');
    // Remove old qr.png when authenticated
    try {
        if (fs.existsSync(QR_FILE_PATH)) {
            fs.unlinkSync(QR_FILE_PATH);
        }
    } catch (e) {}
});

client.on('auth_failure', (msg) => {
    console.error('[✗] Auth failure:', msg);
    clearAuthSession();
});
client.on('ready', () => {
    console.log('✅ WhatsApp connected! Anti-ban layer active');
    global.WA_CONNECTED = true;
  });
  client.on('ready', () => {
    console.log('✅ WhatsApp connected! Anti-ban layer active');
    global.WA_CONNECTED = true;
  });
  client.on('ready', () => {
    console.log('✅ WhatsApp connected! Anti-ban layer active');
    global.WA_CONNECTED = true;
  });
  client.on('ready', () => console.log('[✓] WhatsApp client ready!'));

client.on('message', async (message) => {
    if (message.from.includes('status') || message.from === 'me' || message.isGroup) return;
    console.log(`[IN] ${message.from}: ${message.body.substring(0, 80)}`);

    try {
        const resp = await axios.post(`${AGENT_API_URL}/webhook`, {
            from: message.from.replace('@c.us', ''),
            to: message.to.replace('@c.us', ''),
            body: message.body
        }, { timeout: 30000 });
        if (resp.data.reply) {
            // Anti-ban: show typing indicator for 3-7 sec before replying
            await client.sendPresenceAvailable();
            await randomDelay(SAFETY.typingDelayMs[0], SAFETY.typingDelayMs[1]);
            await safeSend(message.from, resp.data.reply);
            console.log(`[OUT] ${message.from}: ${resp.data.reply.substring(0, 50)}...`);
        }
    } catch (err) {
        if (err.code !== 'ECONNREFUSED') console.error(`[✗] Error: ${err.message}`);
    }
});

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
    if (!checkRateLimit()) return res.status(429).json({ error: 'rate_limit' });
    try {
        await randomDelay(SAFETY.minDelayMs, SAFETY.maxDelayMs);
        const chatId = phone.includes('@c.us') ? phone : `${phone}@c.us`;
        const media = new MessageMedia(mimetype || 'image/png', base64, filename || 'file');
        const r = await // Anti-ban check before sending
  const banCheck = antiBanCheck();
  if (!banCheck.allowed) { console.log('⚠️ Anti-ban:', banCheck.reason); return; }
  await antiBanDelay();
  await humanTypingDelay(text || 'Hello');
  antiBanTrack(false);
  // Anti-ban check before sending
  const banCheck = antiBanCheck();
  if (!banCheck.allowed) { console.log('⚠️ Anti-ban:', banCheck.reason); return; }
  await antiBanDelay();
  await humanTypingDelay(text || 'Hello');
  antiBanTrack(false);
  client.sendMessage(chatId, media, { caption });
        msgCountHour++;
        msgCountDay++;
        res.json({ success: true, messageId: r.id._serialized });
    } catch (e) { res.status(500).json({ error: e.message }); }
});

app.get('/health', (req, res) => {
    res.json({ status: 'ok', whatsapp: client.info ? { number: client.info.wid.user, name: client.info.pushname } : 'disconnected' });
});

const wss = new WebSocketServer({ port: WS_PORT });
wss.on('connection', (ws) => {
    ws.send(JSON.stringify({ type: 'connected', message: 'WhatsApp Bridge Connected' }));
});

app.listen(HTTP_PORT, () => console.log(`[ℹ] Bridge HTTP on :${HTTP_PORT}, WS on :${WS_PORT}`));
client.initialize().catch(err => { console.error('[✗] Init failed:', err); process.exit(1); });