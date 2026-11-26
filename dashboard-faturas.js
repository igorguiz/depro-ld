/* Gestão de Energia — Dashboard 1: Valor mensal das faturas (janela móvel de 60 meses)
 * DEPRO-LD / UTFPR — Sem dependências externas, sem credenciais, sem WebDAV no navegador.
 * Fonte: data/energia.json, preenchido pela sincronização Copel v1.8.2.
 * Integração não invasiva: cria sua seção na aba #energy, sem alterar energy.js.
 */
(() => {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  const WINDOW_MONTHS = 60;
  const MONTH_WIDTH = 63;
  const PLOT_TOP = 58;
  const PLOT_HEIGHT = 252;
  const PLOT_BOTTOM = PLOT_TOP + PLOT_HEIGHT;
  const MARGIN_LEFT = 84;
  const MARGIN_RIGHT = 40;
  const SVG_HEIGHT = 386;
  const ID = 'en-invoice-dashboard';
  const fmtMoney = cents => (cents / 100).toLocaleString('pt-BR', {style: 'currency', currency: 'BRL'});
  const fmtShort = cents => (cents / 100000).toLocaleString('pt-BR', {minimumFractionDigits: 1, maximumFractionDigits: 1});
  const fmtMonth = key => `${key.slice(5, 7)}/${key.slice(2, 4)}`;
  const fmtFullMonth = key => new Date(`${key}-02T12:00:00Z`).toLocaleDateString('pt-BR', {month:'long', year:'numeric', timeZone:'UTC'});
  let hasLoaded = false;
  let lastLoad = 0;
  let inFlight = false;

  const css = `
  #${ID}{margin:22px 0 8px;padding-top:22px;border-top:1px solid var(--border,#e3e5e8)}
  #${ID} h3{margin:0 0 7px;font-size:clamp(17px,2.2vw,22px);line-height:1.3}
  #${ID} .ed-lead{color:#606368;font-size:13px;line-height:1.5;margin:0 0 14px}
  #${ID} .ed-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:11px;margin-bottom:16px}
  #${ID} .ed-stat{background:#f7f7f7;border:1px solid #e4e5e7;border-radius:10px;padding:13px 15px}
  #${ID} .ed-stat small{font-size:12px;color:#666;display:block;margin-bottom:7px}
  #${ID} .ed-stat strong{display:block;font-size:clamp(16px,2.1vw,23px);color:#373435;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
  #${ID} .ed-legend{display:flex;gap:13px 23px;flex-wrap:wrap;align-items:center;margin:9px 0 12px;font-size:13px;color:#404247}
  #${ID} .ed-key{display:inline-flex;align-items:center;gap:8px;white-space:nowrap}
  #${ID} .ed-key-bar{height:14px;width:21px;background:#fecb29;border-radius:3px}
  #${ID} .ed-key-line{height:0;width:26px;border-top:3px solid #303744;position:relative}
  #${ID} .ed-key-line:after{content:"";position:absolute;width:8px;height:8px;border:3px solid #303744;background:#fff;border-radius:50%;top:-7px;left:9px}
  #${ID} .ed-key-average{height:0;width:28px;border-top:3px dashed #8b8e94}
  #${ID} .ed-chart-box{border:1px solid #e1e3e6;background:white;border-radius:11px;overflow:hidden}
  #${ID} .ed-chart-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;padding:11px 14px 4px}
  #${ID} .ed-chart-heading span{font-size:12px;color:#666}
  #${ID} .ed-control{border:1px solid #cbd0d5;background:#fff;color:#373435;border-radius:7px;cursor:pointer;padding:7px 10px;font:600 12px system-ui,sans-serif}
  #${ID} .ed-control:hover{background:#fff8db;border-color:#d5a928}
  #${ID} .ed-control:focus-visible{outline:3px solid #fecb29}
  #${ID} .ed-controls{display:flex;gap:7px}
  #${ID} .ed-plot-area{position:relative}
  #${ID} .ed-yaxis{position:absolute;top:0;left:0;width:77px;height:386px;background:#fff;border-right:1px solid #e1e3e6;pointer-events:none;z-index:1}
  #${ID} .ed-yaxis svg{display:block;height:386px;width:77px}
  #${ID} .ed-scroller{overflow-x:auto;overflow-y:hidden;scrollbar-color:#bbb #f4f4f4;scrollbar-width:thin;scroll-behavior:smooth;max-width:100%;outline-offset:-2px}
  #${ID} .ed-scroller:focus-visible{outline:3px solid #fecb29}
  #${ID} .ed-scroller svg{display:block;max-width:none;height:auto;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
  #${ID} .ed-plot-note{font-size:12px;color:#64666c;margin:0;padding:10px 14px 14px;line-height:1.5}
  #${ID} .ed-plot-note strong{color:#373435}
  #${ID} .ed-error{border:1px solid #efc2b6;background:#fff2ed;color:#8e2915;border-radius:7px;padding:12px;margin:10px 0}
  #${ID} .ed-table-wrap{margin:13px 0 0}
  #${ID} .ed-table-wrap summary{cursor:pointer;font-weight:650;color:#554b25;padding:8px 0}
  #${ID} .ed-table-scroll{overflow-x:auto;max-height:320px;overflow-y:auto;border:1px solid #e4e4e4;border-radius:8px}
  #${ID} table{border-collapse:collapse;width:100%;min-width:390px;font-variant-numeric:tabular-nums}
  #${ID} th,#${ID} td{padding:8px 12px;border-bottom:1px solid #ededed;font-size:12px}
  #${ID} th{position:sticky;top:0;background:#f5f5f5}
  #${ID} th:nth-child(2),#${ID} td:nth-child(2){text-align:right}
  #${ID} th:nth-child(3),#${ID} td:nth-child(3){text-align:left}
  #${ID} .ed-missing td{color:#9a651c;background:#fffaf0}
  #${ID} .ed-svg-tooltip:focus{outline:none}
  #${ID} .ed-svg-tooltip:focus rect.ed-highlight{stroke:#373435;stroke-width:2;fill:#f0cc4b;fill-opacity:.12}
  @media(max-width:650px){#${ID} .ed-cards{grid-template-columns:1fr;gap:7px}#${ID} .ed-stat{padding:10px 12px}#${ID} .ed-legend{font-size:11px;gap:9px}#${ID} .ed-control{padding:7px 8px}}
  `;

  function node(tag, className, text) {
    const el = document.createElement(tag);
    if(className) el.className = className;
    if(text != null) el.textContent = text;
    return el;
  }
  function svgNode(tag, attrs, text) {
    const el = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([k,v]) => el.setAttribute(k, String(v)));
    if(text != null) el.textContent = String(text);
    return el;
  }
  function monthKey(index) {
    const year = Math.floor(index / 12);
    const month = (index % 12) + 1;
    return `${year}-${String(month).padStart(2,'0')}`;
  }
  function monthIndex(key) {return Number(key.slice(0,4))*12 + Number(key.slice(5,7)) - 1;}
  function isValidMonth(key) {return typeof key === 'string' && /^\d{4}-(0[1-9]|1[0-2])$/.test(key);}
  function aggregate(json) {
    const amounts = new Map();
    const invoices = Array.isArray(json?.faturas) ? json.faturas : [];
    for(const bill of invoices) {
      if(bill?.status !== 'ok' || bill.origem_removida || !isValidMonth(bill.mes_consumo)) continue;
      if(bill.valor_centavos == null) continue;
      const cents = Number(bill.valor_centavos);
      if(!Number.isFinite(cents) || cents < 0) continue;
      const key = bill.mes_consumo;
      amounts.set(key, (amounts.get(key) || 0) + Math.round(cents));
    }
    if(!amounts.size) return null;
    const latest = [...amounts.keys()].sort().at(-1);
    const lastIdx = monthIndex(latest);
    const entries = Array.from({length:WINDOW_MONTHS},(_,i) => {
      const key = monthKey(lastIdx - WINDOW_MONTHS + 1 + i);
      return {key, cents:amounts.has(key) ? amounts.get(key) : null};
    });
    const present = entries.filter(e => e.cents !== null);
    const total = present.reduce((sum,e) => sum + e.cents,0);
    const average = Math.round(total / present.length);
    return {entries, latest, count:present.length, total, average, missing:entries.filter(e => e.cents === null)};
  }

  function getAxisScale(data) {
    const greatest = Math.max(data.average,...data.entries.map(e=>e.cents || 0));
    const step = Math.max(1000000,Math.ceil(greatest / 4 / 1000000) * 1000000);
    return {step, maximum:step*4};
  }
  function drawStickyAxis(data) {
    const {step,maximum}=getAxisScale(data);
    const y = cents => PLOT_BOTTOM - (cents / maximum)*PLOT_HEIGHT;
    const svg=svgNode('svg',{width:77,height:SVG_HEIGHT,viewBox:`0 0 77 ${SVG_HEIGHT}`,role:'presentation','aria-hidden':'true'});
    svg.append(svgNode('text',{x:13,y:30,fill:'#5b5d63','font-size':15},'R$'));
    for(let i=0;i<=4;i++) {
      const cents=i*step;
      svg.append(svgNode('text',{x:72,y:y(cents)+4,'text-anchor':'end',fill:'#62666b','font-size':13},cents===0?'0':`${Math.round(cents/100000)} mil`));
    }
    return svg;
  }
  function drawChart(data) {
    const width = MARGIN_LEFT + data.entries.length * MONTH_WIDTH + MARGIN_RIGHT;
    const svg = svgNode('svg', {viewBox:`0 0 ${width} ${SVG_HEIGHT}`,width,height:SVG_HEIGHT,role:'img', 'aria-label': 'Valor bruto mensal das faturas Copel nos últimos 60 meses. Barras amarelas, linha dos valores mensais e média mensal tracejada. Períodos sem fatura não são zero.'});
    const defs = svgNode('defs');
    const gradient = svgNode('linearGradient',{id:'ed-gold-gradient',x1:'0%',y1:'0%',x2:'0%',y2:'100%'});
    gradient.append(svgNode('stop',{offset:'0%','stop-color':'#ffda52'}),svgNode('stop',{offset:'100%','stop-color':'#fecb29'}));
    defs.append(gradient); svg.append(defs);
    const {step,maximum}=getAxisScale(data);
    const y = cents => PLOT_BOTTOM - (cents / maximum)*PLOT_HEIGHT;
    svg.append(svgNode('text',{x:18,y:30,fill:'#5b5d63','font-size':15},'R$'));
    for(let i=0;i<=4;i++) {
      const cents = i * step, yy=y(cents);
      svg.append(svgNode('line',{x1:MARGIN_LEFT,y1:yy,x2:width-MARGIN_RIGHT,y2:yy,stroke:'#dfe0e2','stroke-width':1.2}));
      svg.append(svgNode('text',{x:MARGIN_LEFT-13,y:yy+4,'text-anchor':'end',fill:'#62666b','font-size':13}, cents===0?'0':`${Math.round(cents/100000)} mil`));
    }

    // Falta de PDF válido = lacuna de dados, nunca valor financeiro zero.
    data.entries.forEach((e,i) => {
      if(e.cents !== null) return;
      const x = MARGIN_LEFT + i*MONTH_WIDTH;
      svg.append(svgNode('rect',{x:x+5,y:PLOT_TOP,width:MONTH_WIDTH-10,height:PLOT_HEIGHT,fill:'#fff8e8'}));
      svg.append(svgNode('text',{x:x+MONTH_WIDTH/2,y:PLOT_TOP+20,'text-anchor':'middle',fill:'#a06c15','font-size':11},'s/d'));
    });

    data.entries.forEach((e,i) => {
      if(e.cents === null) return;
      const center = MARGIN_LEFT+i*MONTH_WIDTH + MONTH_WIDTH/2;
      const yy=y(e.cents);
      svg.append(svgNode('rect',{x:center-18,y:yy,width:36,height:Math.max(0,PLOT_BOTTOM-yy),rx:2,fill:'url(#ed-gold-gradient)'}));
    });

    const avgY=y(data.average);
    svg.append(svgNode('line',{x1:MARGIN_LEFT,y1:avgY,x2:width-MARGIN_RIGHT,y2:avgY,stroke:'#8c8e93','stroke-width':3,'stroke-dasharray':'10 8'}));

    let segment=[];
    function flush() {
      if(segment.length >= 2) svg.append(svgNode('polyline',{points:segment.join(' '),fill:'none',stroke:'#303744','stroke-width':3.2,'stroke-linecap':'round','stroke-linejoin':'round'}));
      segment=[];
    }
    data.entries.forEach((e,i) => {
      if(e.cents === null) {flush();return;}
      segment.push(`${MARGIN_LEFT+i*MONTH_WIDTH+MONTH_WIDTH/2},${y(e.cents)}`);
    });
    flush();

    data.entries.forEach((e,i) => {
      const center = MARGIN_LEFT+i*MONTH_WIDTH+MONTH_WIDTH/2;
      if(e.cents !== null) {
        const yy=y(e.cents);
        const group=svgNode('g',{class:'ed-svg-tooltip',tabindex:0,role:'group','aria-label':`${fmtFullMonth(e.key)}: ${fmtMoney(e.cents)}`});
        group.append(svgNode('rect',{class:'ed-highlight',x:center-27,y:PLOT_TOP,width:54,height:PLOT_HEIGHT,fill:'transparent'}));
        group.append(svgNode('circle',{cx:center,cy:yy,r:6.8,fill:'#fff',stroke:'#303744','stroke-width':3}));
        // Um número em cada competência, como no gráfico fornecido pelo usuário.
        group.append(svgNode('text',{x:center,y:Math.max(24,yy-16),'text-anchor':'middle',fill:'#222','font-size':12.5,'font-weight':650},fmtShort(e.cents)));
        group.append(svgNode('title',{},`${fmtFullMonth(e.key)} — ${fmtMoney(e.cents)}`));
        svg.append(group);
      }
      const label=svgNode('text',{x:center,y:PLOT_BOTTOM+29,'text-anchor':'end',transform:`rotate(-45 ${center} ${PLOT_BOTTOM+29})`,fill:e.cents===null?'#9f6e1e':'#44474e','font-size':12.5},fmtMonth(e.key));
      svg.append(label);
    });
    svg.append(svgNode('text',{x:MARGIN_LEFT+data.entries.length*MONTH_WIDTH/2,y:SVG_HEIGHT-10,'text-anchor':'middle',fill:'#53575c','font-size':14},'Mês de consumo (data da leitura)'));
    return svg;
  }

  function show(data) {
    const dashboard=document.getElementById(ID);
    if(!dashboard) return;
    const subtitle=dashboard.querySelector('[data-ed="subtitle"]');
    const total=dashboard.querySelector('[data-ed="total"]');
    const mean=dashboard.querySelector('[data-ed="average"]');
    const recent=dashboard.querySelector('[data-ed="recent"]');
    const frame=dashboard.querySelector('[data-ed="chart"]');
    const yaxis=dashboard.querySelector('[data-ed="yaxis"]');
    const note=dashboard.querySelector('[data-ed="note"]');
    const tbody=dashboard.querySelector('[data-ed="table"]');
    const start=data.entries[0].key;
    subtitle.textContent=`Janela móvel: ${fmtFullMonth(start)} a ${fmtFullMonth(data.latest)} · ${data.count} de 60 meses com fatura validada.`;
    total.textContent=fmtMoney(data.total);
    mean.textContent=fmtMoney(data.average);
    const newest=data.entries.at(-1);
    recent.textContent=newest.cents===null?'Sem dados':fmtMoney(newest.cents);
    frame.replaceChildren(drawChart(data));
    yaxis.replaceChildren(drawStickyAxis(data));
    const missing=data.missing.map(e=>fmtFullMonth(e.key));
    note.textContent=missing.length
      ? `Média calculada somente sobre os ${data.count} meses com dados. Sem fatura validada: ${missing.join(', ')}. Meses ausentes não foram tratados como R$ 0,00. Deslize horizontalmente para consultar os 5 anos.`
      : `Média calculada sobre os 60 meses com dados. Deslize horizontalmente para consultar os 5 anos.`;
    tbody.replaceChildren();
    data.entries.forEach(e=>{
      const tr=document.createElement('tr');
      if(e.cents===null)tr.className='ed-missing';
      [fmtFullMonth(e.key),e.cents===null?'—':fmtMoney(e.cents),e.cents===null?'Sem fatura validada':'Validada'].forEach(s=>tr.append(node('td','',s)));
      tbody.append(tr);
    });
    // Após carregar, posiciona o gráfico nos meses mais recentes; demais meses ficam acessíveis pela barra horizontal.
    frame.style.scrollBehavior='auto';
    frame.scrollLeft=frame.scrollWidth;
    frame.style.scrollBehavior='';
    document.getElementById(ID).querySelector('[data-ed="error"]').hidden=true;
  }

  function showError(message) {
    const el=document.querySelector(`#${ID} [data-ed="error"]`);
    if(!el)return;
    el.textContent=message;
    el.hidden=false;
  }
  async function refresh(force=false) {
    if(inFlight || (!force&&hasLoaded && Date.now()-lastLoad<120000))return;
    inFlight=true;
    const el=document.querySelector(`#${ID} [data-ed="subtitle"]`);
    if(el && !hasLoaded)el.textContent='Carregando os dados publicados da Copel...';
    try {
      const response=await fetch(`data/energia.json?v=${Date.now()}`,{cache:'no-store'});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      const json=await response.json();
      const data=aggregate(json);
      if(!data)throw new Error('Não foram encontradas faturas validadas com valor e mês de consumo.');
      show(data);
      hasLoaded=true;
      lastLoad=Date.now();
    } catch(e) {
      showError(`Não foi possível atualizar o gráfico de valores das faturas: ${e.message}`);
      if(el&&!hasLoaded)el.textContent='Dados indisponíveis';
    } finally {inFlight=false;}
  }

  function mount() {
    const panel=document.getElementById('energy');
    if(!panel || document.getElementById(ID))return;
    const style=node('style');style.textContent=css;document.head.append(style);
    const section=node('section');section.id=ID;
    const heading=node('h3','','Valor mensal das faturas de energia elétrica');section.append(heading);
    const subtitle=node('p','ed-lead','Exibindo as 60 competências mais recentes disponíveis.');subtitle.dataset.ed='subtitle';section.append(subtitle);
    const cards=node('div','ed-cards');
    [['Total da janela','total'],['Média mensal (meses com dados)','average'],['Fatura mais recente','recent']].forEach(([label,key])=>{
      const card=node('div','ed-stat');card.append(node('small','',label));
      const val=node('strong','','—');val.dataset.ed=key;card.append(val);cards.append(card);
    });section.append(cards);
    const legend=node('div','ed-legend');
    [['ed-key-bar','Valor da fatura'],['ed-key-line','Valor mensal'],['ed-key-average','Média mensal']].forEach(([symbol,label])=>{
      const item=node('span','ed-key');item.append(node('span',symbol),document.createTextNode(label));legend.append(item);
    });section.append(legend);
    const wrapper=node('div','ed-chart-box');
    const chartHead=node('div','ed-chart-heading');chartHead.append(node('span','','R$ · 60 meses · Mês de consumo'));
    const controls=node('div','ed-controls');
    const back=node('button','ed-control','← 12 meses');back.type='button';back.setAttribute('aria-label','Voltar doze meses no gráfico');
    const forward=node('button','ed-control','12 meses →');forward.type='button';forward.setAttribute('aria-label','Avançar doze meses no gráfico');
    controls.append(back,forward);chartHead.append(controls);wrapper.append(chartHead);
    const plotArea=node('div','ed-plot-area');
    const scroller=node('div','ed-scroller');scroller.dataset.ed='chart';scroller.tabIndex=0;scroller.setAttribute('role','region');scroller.setAttribute('aria-label','Gráfico de barras e linha com rolagem horizontal dos últimos 60 meses');
    plotArea.append(scroller);
    const stickyAxis=node('div','ed-yaxis');stickyAxis.dataset.ed='yaxis';stickyAxis.setAttribute('aria-hidden','true');plotArea.append(stickyAxis);
    wrapper.append(plotArea);
    const plotNote=node('p','ed-plot-note','Aguardando dados.');plotNote.dataset.ed='note';wrapper.append(plotNote);section.append(wrapper);
    back.addEventListener('click',()=>scroller.scrollBy({left:-MONTH_WIDTH*12,behavior:'smooth'}));
    forward.addEventListener('click',()=>scroller.scrollBy({left:MONTH_WIDTH*12,behavior:'smooth'}));
    const err=node('p','ed-error');err.dataset.ed='error';err.hidden=true;section.append(err);
    const details=node('details','ed-table-wrap');details.append(node('summary','','Conferir valores mensais em tabela (60 meses)'));
    const tableWrap=node('div','ed-table-scroll');
    const table=node('table');
    const thead=node('thead');const row=node('tr');
    ['Mês de consumo','Valor da fatura','Situação'].forEach(t=>row.append(node('th','',t)));
    thead.append(row);table.append(thead);
    const body=node('tbody');body.dataset.ed='table';table.append(body);tableWrap.append(table);details.append(tableWrap);section.append(details);
    const before=panel.querySelector('.en-filters') || panel.querySelector('.section');
    if(before)panel.insertBefore(section,before);else panel.append(section);
    const modButton=document.getElementById('mod-energy');
    if(modButton)modButton.addEventListener('click',()=>refresh());
    const refreshButton=document.getElementById('en-refresh');
    if(refreshButton)refreshButton.addEventListener('click',()=>refresh(true));
    if(!panel.hidden)refresh();
    setInterval(()=>{if(!panel.hidden)refresh();},5*60*1000);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});
  else mount();
})();
