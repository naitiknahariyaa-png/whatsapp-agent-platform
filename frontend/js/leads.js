async function api(path, opts={}){ const res=await fetch(path, opts); let txt=''; try{ txt=await res.text() }catch(e){} let data=null; try{ data = txt?JSON.parse(txt):null }catch(e){ data=txt } return {ok:res.ok, status:res.status, data}}
function $(id){return document.getElementById(id)}

async function loadLeads(){
  const status = $('filterStatus').value;
  const r = await api('/api/crm/leads'+(status?('?status='+encodeURIComponent(status)):''), {method:'GET'});
  if(!r.ok){ alert('Failed to load leads'); return; }
  const rows = r.data.leads || [];
  const tbody = document.querySelector('#leadsTable tbody'); tbody.innerHTML='';
  rows.forEach(rw=>{
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${rw.id}</td><td>${rw.phone}</td><td>${rw.name||''}</td><td>${rw.score||0}</td><td>${rw.status}</td><td><button data-id="${rw.id}" class="viewBtn">View</button> <button data-id="${rw.id}" class="toQualified">Mark Qualified</button></td>`;
    tbody.appendChild(tr);
  });
  document.querySelectorAll('.viewBtn').forEach(b=>b.addEventListener('click', ()=>viewLead(b.dataset.id)));
  document.querySelectorAll('.toQualified').forEach(b=>b.addEventListener('click', ()=>updateStatus(b.dataset.id,'qualified')));
}

async function viewLead(id){ const r = await api('/api/crm/leads/'+id); if(!r.ok){ alert('Failed'); return;} const d=r.data; alert(JSON.stringify(d,null,2)); }
async function updateStatus(id, status){ const r = await api('/api/crm/leads/'+id+'/status',{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status})}); if(!r.ok){ alert('Failed: '+JSON.stringify(r.data)); return;} loadLeads(); }

async function createLead(){ const phone=$('cPhone').value.trim(); if(!phone){ $('createMsg').innerText='Phone required'; return;} const name=$('cName').value; const source=$('cSource').value; $('createLeadBtn').disabled=true; const r = await api('/api/crm/leads',{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({phone_number:phone,name,source})}); $('createLeadBtn').disabled=false; if(!r.ok){ $('createMsg').innerText='Create failed'; return;} $('createMsg').innerText='Created'; loadLeads(); }

document.addEventListener('DOMContentLoaded', ()=>{
  $('refreshLeads').addEventListener('click', loadLeads);
  $('filterStatus').addEventListener('change', loadLeads);
  $('openCreate').addEventListener('click', ()=>$('createModal').style.display='block');
  $('closeCreate').addEventListener('click', ()=>$('createModal').style.display='none');
  $('createLeadBtn').addEventListener('click', createLead);
  loadLeads();
});
