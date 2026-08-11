/**
 * WhatsApp Agent Platform — Web Chat Widget
 * Embed: <script src="http://your-domain.com/widget.js?biz=YOUR_BIZ_ID"></script>
 */
(function() {
  'use strict';

  var API_BASE = window.location.origin;
  var BIZ_ID = 'default';
  var params = new URLSearchParams(window.location.search);
  if (params.get('biz')) BIZ_ID = params.get('biz');

  var WIDGET_ID = 'wap-widget-' + BIZ_ID;
  if (document.getElementById(WIDGET_ID)) return;

  // Styles
  var css = '.wap-widget-launcher{position:fixed;bottom:24px;right:24px;width:60px;height:60px;border-radius:50%;background:#25D366;color:#fff;border:none;font-size:24px;cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,0.3);z-index:9999;display:flex;align-items:center;justify-content:center;transition:all .3s}.wap-widget-launcher:hover{transform:scale(1.1)}.wap-widget-window{position:fixed;bottom:100px;right:24px;width:360px;max-width:calc(100vw - 48px);height:420px;background:#fff;border-radius:16px;box-shadow:0 8px 32px rgba(0,0,0,0.15);border:1px solid #e5e5e5;z-index:9999;display:none;flex-direction:column;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif}.wap-widget-window.open{display:flex}.wap-widget-header{background:#25D366;color:#fff;padding:14px 18px;font-weight:700;font-size:15px;display:flex;align-items:center;justify-content:space-between}.wap-widget-header .wap-close{cursor:pointer;font-size:20px;line-height:1}.wap-widget-messages{flex:1;overflow-y:auto;padding:14px;background:#f9f9f9}.wap-widget-msg{padding:10px 14px;margin-bottom:10px;border-radius:14px;font-size:13px;line-height:1.5;max-width:82%;word-wrap:break-word}.wap-widget-msg.bot{background:#fff;margin-right:auto;border:1px solid #e5e5e5}.wap-widget-msg.user{background:#25D366;color:#fff;margin-left:auto;text-align:right}.wap-widget-input{display:flex;gap:8px;padding:10px 12px;border-top:1px solid #e5e5e5;background:#fff}.wap-widget-input input{flex:1;padding:10px 14px;border:2px solid #e5e5e5;border-radius:20px;font-size:13px;outline:none;background:#f9f9f9}.wap-widget-input input:focus{border-color:#25D366}.wap-widget-input button{background:#25D366;color:#fff;border:none;padding:8px 16px;border-radius:20px;font-size:13px;font-weight:600;cursor:pointer}.wap-widget-typing{font-size:11px;color:#888;padding:4px 14px;display:none}';
  var style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  // Container
  var container = document.createElement('div');
  container.id = WIDGET_ID;

  var launcher = document.createElement('button');
  launcher.className = 'wap-widget-launcher';
  launcher.innerHTML = '💬';
  launcher.setAttribute('aria-label', 'Chat with us');

  var window_ = document.createElement('div');
  window_.className = 'wap-widget-window';
  window_.innerHTML = '<div class="wap-widget-header"><span>Chat with us</span><span class="wap-close">&times;</span></div>' +
    '<div class="wap-widget-messages" id="wap-msgs-' + BIZ_ID + '"></div>' +
    '<div class="wap-widget-typing" id="wap-typing-' + BIZ_ID + '">Assistant is typing...</div>' +
    '<div class="wap-widget-input"><input type="text" id="wap-input-' + BIZ_ID + '" placeholder="Type a message..." /><button id="wap-send-' + BIZ_ID + '">Send</button></div>';

  container.appendChild(launcher);
  container.appendChild(window_);
  document.body.appendChild(container);

  var messagesEl = window_.querySelector('.wap-widget-messages');
  var inputEl = window_.querySelector('input');
  var sendBtn = window_.querySelector('button');
  var typingEl = window_.querySelector('.wap-widget-typing');

  function addMsg(text, sender) {
    var div = document.createElement('div');
    div.className = 'wap-widget-msg ' + sender;
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function toggle() {
    window_.classList.toggle('open');
    if (window_.classList.contains('open')) {
      setTimeout(function() { messagesEl.scrollTop = messagesEl.scrollHeight; }, 200);
    }
  }

  launcher.addEventListener('click', toggle);
  window_.querySelector('.wap-close').addEventListener('click', toggle);

  async function send() {
    var msg = inputEl.value.trim();
    if (!msg) return;
    addMsg(msg, 'user');
    inputEl.value = '';
    typingEl.style.display = 'block';

    try {
      var resp = await fetch(API_BASE + '/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ business_id: BIZ_ID, message: msg, customer_id: 'web_' + BIZ_ID, client_id: 1 })
      });
      var data = await resp.json();
      typingEl.style.display = 'none';
      if (data.reply_to_customer) {
        addMsg(data.reply_to_customer, 'bot');
      } else {
        addMsg('Thanks for your message!', 'bot');
      }
    } catch (e) {
      typingEl.style.display = 'none';
      addMsg('Sorry, something went wrong. Please try again.', 'bot');
    }
  }

  sendBtn.addEventListener('click', send);
  inputEl.addEventListener('keydown', function(e) { if (e.key === 'Enter') send(); });

  // Welcome message
  addMsg('Hi! How can I help you today?', 'bot');
})();
