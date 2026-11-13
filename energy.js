"use strict";
// Renderização exclusivamente de JSON publicado pelo workflow; nenhuma credencial WebDAV no navegador.
(() => {
  const byId = id => document.getElementById(id);
  const energyState = {invoices: [],status: null,loaded:false};
  const fmt = n => Number(n).toLocaleString('pt-BR', {maximumFractionDigits:2});
  const money = cents => (Number(cents)/100).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
  const clear = id => byId(id).replaceChildren();
  const fill = (id, value) => {byId(id).textContent = value;};
  const string = raw => (raw == null ? '—' : String(raw));

  function setFilters(items) {
    const years = [...new Set(items.map(i => (i.competencia || '').slice(0,4)).filter(x => /^20\d\d$/.test(x)))].sort().reverse();
    const units = [...new Set(items.map(i=>i.unidade).filter(Boolean))].sort();
    const yearSelect = byId('en-year'), unitSelect = byId('en-unit');
    const year = yearSelect.value, unit = unitSelect.value;
    yearSelect.replaceChildren(new Option('Todos os anos', ''));
    years.forEach(v => yearSelect.add(new Option(v,v)));
    if(years.includes(year)) yearSelect.value = year;
    unitSelect.replaceChildren(new Option('Todas as unidades', ''));
    units.forEach(u => unitSelect.add(new Option(u,u)));
    if(units.includes(unit)) unitSelect.value = unit;
  }

  function getVisible() {
    const year=byId('en-year').value,month=byId('en-month').value,unit=byId('en-unit').value;
    return energyState.invoices.filter(b=> (!year||b.competencia?.startsWith(year)) && (!month||b.competencia?.slice(5,7)===month) && (!unit||b.unidade===unit));
  }
  function addCell(row, val) {const td=document.createElement('td');td.textContent=string(val);row.append(td);}
  function render() {
    const visible=getVisible();
    const ok=visible.filter(b=>b.status==='ok'&&!b.origem_removida);
    const pending=visible.filter(b=>b.status!=='ok'||b.origem_removida);
    const kwh=ok.reduce((acc,b)=>acc+Number(b.consumo_kwh||0),0);
    const cents=ok.reduce((acc,b)=>acc+Number(b.valor_centavos||0),0);
    fill('en-invoices',String(ok.length));
    fill('en-pending',String(pending.length));
    fill('en-kwh',ok.length?fmt(kwh)+' kWh':'—');
    fill('en-total',ok.length?money(cents):'—');
    fill('en-average',ok.length&&kwh>0?money(Math.round(cents/kwh))+'/kWh':'—');
    const selectedPeriod=(byId('en-year').value || 'todo o histórico') + (byId('en-month').value?'/'+byId('en-month').value:'');
    fill('en-view','Período: '+selectedPeriod+' · Apenas faturas validadas entram nos totais.');

    const months=new Map();
    for(const bill of ok) {
      const key=bill.competencia;
      const entry=months.get(key)||{kwh:0,cents:0,n:0};
      entry.kwh+=Number(bill.consumo_kwh);
      entry.cents+=Number(bill.valor_centavos);
      entry.n++;
      months.set(key,entry);
    }
    const ordered=[...months].sort((a,b)=>a[0].localeCompare(b[0]));
    const chart=byId('en-chart');chart.replaceChildren();
    if(!ordered.length){const note=document.createElement('p');note.className='note';note.textContent='Ainda não há consumo validado neste período.';chart.append(note);}
    else {
      const recent=ordered.slice(-18), max=Math.max(...recent.map(([,e])=>e.kwh),1);
      for(const [month,v] of recent) {
        const bar=document.createElement('div');bar.className='en-bar';
        const name=document.createElement('span');name.textContent=month.slice(5)+'/'+month.slice(0,4);
        const track=document.createElement('div');track.className='en-track';track.setAttribute('role','img');track.setAttribute('aria-label',`${month}: ${fmt(v.kwh)} kWh`);
        const fillBar=document.createElement('div');fillBar.className='en-fill';fillBar.style.width=(v.kwh/max*100)+'%';track.append(fillBar);
        const value=document.createElement('strong');value.textContent=fmt(v.kwh)+' kWh';
        bar.append(name,track,value);chart.append(bar);
      }
    }
    const monthsBody=byId('en-months');monthsBody.replaceChildren();
    for(const [month,v] of ordered.reverse()) {
      const tr=document.createElement('tr');[month,v.n,fmt(v.kwh)+' kWh',money(v.cents)].forEach(item=>addCell(tr,item));monthsBody.append(tr);
    }
    const billsBody=byId('en-bills');billsBody.replaceChildren();
    const bills=[...visible].sort((a,b)=>(b.competencia||'').localeCompare(a.competencia||''));
    for(const bill of bills.slice(0,200)) {
      const tr=document.createElement('tr');
      if(bill.status!=='ok'||bill.origem_removida) tr.className='en-review';
      const status=bill.origem_removida?'Origem ausente':bill.status==='ok'?'Validada':'Conferir';
      [bill.competencia||'—',bill.unidade||'—',bill.consumo_kwh==null?'—':fmt(bill.consumo_kwh),
       bill.valor_centavos==null?'—':money(bill.valor_centavos),status,bill.motivo||'—'].forEach(v=>addCell(tr,v));
      billsBody.append(tr);
    }
    fill('en-table-notice',bills.length>200?'Exibindo as 200 faturas mais recentes do filtro.':'');
  }

  async function fetchJson(path) {
    const res=await fetch(path+'?t='+Date.now(),{cache:'no-store'});
    if(!res.ok) throw new Error('HTTP '+res.status);
    return res.json();
  }
  async function refreshEnergy() {
    const refreshBtn=byId('en-refresh');
    if(refreshBtn.disabled) return;
    refreshBtn.disabled=true;
    fill('en-status','Carregando dados publicados...');
    try {
      const [data,status]=await Promise.all([fetchJson('data/energia.json'),fetchJson('data/energia_status.json')]);
      energyState.invoices=Array.isArray(data.faturas)?data.faturas:[];
      energyState.status=status;
      energyState.loaded=true;
      setFilters(energyState.invoices);
      const state=string(status.estado);
      byId('en-state').className='en-state '+(state==='sucesso'?'en-success':state==='erro'?'en-error':'en-wait');
      byId('en-state').textContent=state==='sucesso'?'Sincronizado':state==='erro'?'Falha na consulta':'Aguardando primeira sincronização';
      fill('en-status',status.mensagem||'Estado não disponível');
      fill('en-updated',status.ultima_sincronizacao?new Date(status.ultima_sincronizacao).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'}):'Ainda não sincronizado');
      fill('en-found',String(status.arquivos_localizados??0));
      fill('en-new',String(status.novos_ou_alterados??0));
      render();
    } catch (e) {
      fill('en-status','Falha ao ler os arquivos de dados publicados: '+e.message);
      byId('en-state').textContent='Dados indisponíveis';
      byId('en-state').className='en-state en-error';
    } finally {
      refreshBtn.disabled=false;
    }
  }
  byId('mod-energy').addEventListener('click',refreshEnergy);
  byId('en-refresh').addEventListener('click',refreshEnergy);
  for (const id of ['en-year','en-month','en-unit']) byId(id).addEventListener('change',render);
  // Este ciclo recarrega o JSON; a verificação efetiva do WebDAV é feita pelo Actions a cada 6 h.
  setInterval(()=>{if(!byId('energy').hidden)refreshEnergy();},5*60*1000);
})();
