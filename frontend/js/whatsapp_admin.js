async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let txt = '';
  try { txt = await res.text(); } catch(e){}
  let data = null;
  try { data = txt ? JSON.parse(txt) : null; } catch(e) { data = txt; }
  return { ok: res.ok, status: res.status, data };
}

function $(id){return document.getElementById(id)}

async function updateStatus(){
  const s = await api('/api/whatsapp/bridge/status');
  if(!s.ok){ $('bridgeState').innerText='offline'; $('connected').innerText='false'; return; }
  const st = s.data || {};
  $('bridgeState').innerText = st.connection_state || (st.bridge_online ? 'online' : 'unknown');
  $('connected').innerText = st.connected ? 'true' : 'false';
  $('phone').innerText = (st.connection_info && st.connection_info.number) || st.phone_number || '-';
}

async function loadQr(){
  const status = await api('/api/whatsapp/bridge/status');
  if(status.ok && status.data && status.data.connected){
    $('qrMessage').innerText = 'WhatsApp already connected: ' + ((status.data.connection_info && status.data.connection_info.number) || status.data.phone_number || 'unknown');
    $('qrImg').style.display='none';
    return;
  }
  const r = await api('/api/whatsapp/bridge-qr');
  if(!r.ok){ $('qrMessage').innerText = 'QR fetch failed'; $('qrImg').style.display='none'; return; }
  const d = r.data || {};
  const qrImage = d.qr_image || d.qr_data_url || d.data_url;
  if(qrImage){ $('qrImg').src = qrImage; $('qrImg').style.display='block'; $('qrMessage').innerText = d.message || 'Scan QR'; return; }
  if(d.status === 'waiting'){
    $('qrMessage').innerText = d.message || 'Waiting for QR...';
    $('qrImg').style.display='none';
    return;
  }
  if(d.status === 'connected' || d.connected){
    $('qrMessage').innerText = d.message || 'Already connected';
    $('qrImg').style.display='none';
    return;
  }
  if(d.qr){ $('qrMessage').innerText = d.qr; $('qrImg').style.display='none'; return; }
  $('qrMessage').innerText = d.message || 'No QR available'; $('qrImg').style.display='none';
}

async function startBridge(){
  $('start').disabled = true;
  const r = await api('/api/whatsapp/bridge/start',{method:'POST'});
  $('start').disabled = false;
  if(r.ok){ await updateStatus(); setTimeout(loadQr,1000); }
  else alert('Failed to start bridge: '+(r.data?.message||r.status));
}

async function stopBridge(){
  const r = await api('/api/whatsapp/bridge/stop',{method:'POST'});
  if(r.ok){ await updateStatus(); $('qrImg').style.display='none'; $('qrMessage').innerText='Bridge stopped'; }
  else alert('Failed to stop bridge');
}

async function refreshQr(){
  const r = await api('/api/whatsapp/bridge/refresh',{method:'POST'});
  if(r.ok){ setTimeout(loadQr,800); }
  else alert('Refresh failed: '+JSON.stringify(r.data || r.status));
}

async function resetSession(){
  if(!confirm('Reset the WhatsApp session? This will clear the current connected account and require a fresh QR scan.')) return;
  const r = await api('/api/whatsapp/bridge/reset',{method:'POST'});
  if(r.ok){ $('qrMessage').innerText = 'Resetting bridge session...'; $('qrImg').style.display='none'; setTimeout(loadQr,1500); }
  else alert('Reset failed: '+JSON.stringify(r.data || r.status));
}

async function sendTest(){
  const to = $('testTo').value.trim();
  const message = $('testMessage').value || 'Test message';
  if(!to){ $('sendResult').innerText = 'Enter phone number'; return; }
  // prefer authenticated send; fallback to local test-send
  const token = localStorage.getItem('api_token');
  let headers = {'Content-Type':'application/json'};
  if(token) headers['Authorization'] = 'Bearer ' + token;
  const r = await api('/api/broadcast/send-contact',{method:'POST', headers:headers, body:JSON.stringify({phone_number: to, message: message})});
  if(r.ok){ $('sendResult').innerText = 'Sent (queued)'; }
  else { $('sendResult').innerText = JSON.stringify(r.data || r.status); }
}

async function login(){
  const email = $('loginEmail').value.trim();
  const password = $('loginPassword').value;
  if(!email || !password){ $('loginMsg').innerText='Email+password required'; return; }
  const r = await api('/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({email,password})});
  if(r.ok && r.data && r.data.access_token){
    localStorage.setItem('api_token', r.data.access_token);
    $('loginMsg').innerText = 'Logged in';
    $('logoutBtn').style.display = 'inline-block';
    $('loginBtn').style.display = 'none';
  } else {
    $('loginMsg').innerText = 'Login failed';
  }
}

function logout(){
  localStorage.removeItem('api_token');
  $('loginMsg').innerText = 'Logged out';
  $('logoutBtn').style.display = 'none';
  $('loginBtn').style.display = 'inline-block';
}

async function saveMeta(){
  const token = $('metaToken').value.trim();
  const phoneId = $('metaPhoneId').value.trim();
  if(!token || !phoneId){ $('metaResult').innerText='Both token and phone id required'; return; }
  const apiToken = localStorage.getItem('api_token');
  if(!apiToken){ $('metaResult').innerText='Login required to save'; return; }
  $('saveMeta').disabled = true;
  const r = await api('/api/keys/save', {method:'POST', headers:{'Content-Type':'application/json','Authorization':'Bearer '+apiToken}, body:JSON.stringify({key_name:'whatsapp_api_key', key_value: token})});
  // also save phone id into business profile endpoint
  if(r.ok){
    // attempt to save phone id into business profile via /api/me/business
    const biz = await api('/api/me/business', {method:'POST', headers:{'Content-Type':'application/json','Authorization':'Bearer '+apiToken}, body:JSON.stringify({contact_phone: '', meta_phone_number_id: phoneId})});
    $('metaResult').innerText = 'Saved (check business profile)';
    loadKeys();
  } else {
    $('metaResult').innerText = 'Save failed: '+JSON.stringify(r.data||r.status);
  }
  $('saveMeta').disabled = false;
}

async function testMeta(){
  const apiToken = localStorage.getItem('api_token');
  if(!apiToken){ $('metaResult').innerText='Login required to test'; return; }
  const phone = $('testTo').value.trim();
  if(!phone){ $('metaResult').innerText='Enter phone in Send Test field'; return; }
  const r = await api('/api/whatsapp/meta/test-send', {method:'POST', headers:{'Content-Type':'application/json','Authorization':'Bearer '+apiToken}, body:JSON.stringify({phone_number: phone, message: $('testMessage').value})});
  $('metaResult').innerText = JSON.stringify(r.data || r.status);
}

async function loadHealth(){
  const r = await api('/api/whatsapp/bridge-health');
  if(!r.ok){ $('health').innerText = 'Health check failed'; return; }
  $('health').innerText = JSON.stringify(r.data, null, 2);
}

async function loadKeys(){
  const token = localStorage.getItem('api_token');
  if(!token){ $('wh_key').innerText='(login required)'; $('tg_key').innerText='(login required)'; return; }
  const r = await api('/api/keys', {method:'GET', headers:{'Authorization':'Bearer '+token}});
  if(!r.ok){ $('keysMsg').innerText='Could not load keys'; return; }
  const keys = r.data.keys || {};
  $('wh_key').innerText = keys.whatsapp_api_key || '(not set)';
  $('tg_key').innerText = keys.telegram_bot_token || '(not set)';
}

async function showKey(keyName, targetId){
  const token = localStorage.getItem('api_token');
  if(!token){ alert('Login required'); return; }
  const btn = document.querySelector(`#${targetId}`).nextElementSibling;
  btn.disabled = true;
  const r = await api('/api/keys/get', {method:'POST', headers:{'Content-Type':'application/json','Authorization':'Bearer '+token}, body:JSON.stringify({key_name: keyName})});
  if(r.ok && r.data){
    const val = r.data.value || '';
    alert(keyName + ': ' + val);
  } else {
    alert('Could not retrieve key: '+JSON.stringify(r.data||r.status));
  }
  btn.disabled = false;
}

document.addEventListener('DOMContentLoaded', ()=>{
  $('start').addEventListener('click', startBridge);
  $('stop').addEventListener('click', stopBridge);
  $('refresh').addEventListener('click', refreshQr);
  const resetBtn = $('reset');
  if (resetBtn) { resetBtn.addEventListener('click', resetSession); }
  $('statusBtn').addEventListener('click', updateStatus);
  $('loginBtn').addEventListener('click', login);
  $('logoutBtn').addEventListener('click', logout);
  $('saveMeta').addEventListener('click', saveMeta);
  $('testMeta').addEventListener('click', testMeta);
  $('showWhKey').addEventListener('click', ()=>showKey('whatsapp_api_key','wh_key'));
  $('showTgKey').addEventListener('click', ()=>showKey('telegram_bot_token','tg_key'));
  setInterval(loadHealth, 5000);
  $('sendTest').addEventListener('click', sendTest);
  updateStatus(); loadQr();
  setInterval(updateStatus,5000);
  loadHealth();
  loadKeys();
});
