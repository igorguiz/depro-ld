/* Gestão de Energia — Dashboard v1.2: faturas, demanda e consumo (janela móvel de 60 meses)
 * DEPRO-LD / UTFPR — Sem dependências externas, sem credenciais, sem WebDAV no navegador.
 * Fonte: data/energia.json, preenchido pela sincronização Copel v1.8.2.
 * Integração não invasiva: três gráficos na aba #energy. Sem indicadores-resumo ou tabela.
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
  const GREEN = '#248a55'; // Consumo na ponta
  const RED = '#d14646';   // Consumo fora de ponta
  const CONTRACT = '#187d93';
  const fmtMoney = cents => (cents / 100).toLocaleString('pt-BR', {style: 'currency', currency: 'BRL'});
  const fmtShort = cents => (cents / 100000).toLocaleString('pt-BR', {minimumFractionDigits: 1, maximumFractionDigits: 1});
  const fmtMonth = key => `${key.slice(5, 7)}/${key.slice(2, 4)}`;
  const fmtFullMonth = key => new Date(`${key}-02T12:00:00Z`).toLocaleDateString('pt-BR', {month:'long', year:'numeric', timeZone:'UTC'});
  const fmtNumber = (value, decimals=2) => Number(value).toLocaleString('pt-BR', {minimumFractionDigits:decimals, maximumFractionDigits:decimals});
  const fmtThousand = value => (Number(value)/1000).toLocaleString('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1});
  let hasLoaded = false;
  let lastLoad = 0;
  let inFlight = false;

  const css = `
  #${ID}{margin:22px 0 8px;padding-top:22px;border-top:1px solid var(--border,#e3e5e8)}
  #${ID} h3{margin:0 0 7px;font-size:clamp(17px,2.2vw,22px);line-height:1.3}
  #${ID} .ed-lead{color:#606368;font-size:13px;line-height:1.5;margin:0 0 14px}
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
  #${ID} .ed-subsection{margin-top:29px;padding-top:26px;border-top:1px solid #e1e3e6}
  #${ID} .ed-key-contract{width:27px;height:0;border-top:3px solid ${CONTRACT}}
  #${ID} .ed-key-green{height:14px;width:21px;background:${GREEN};border-radius:3px}
  #${ID} .ed-key-red{height:14px;width:21px;background:${RED};border-radius:3px}
  #${ID} .ed-svg-tooltip:focus{outline:none}
  #${ID} .ed-svg-tooltip:focus rect.ed-highlight{stroke:#373435;stroke-width:2;fill:#f0cc4b;fill-opacity:.12}
  @media(max-width:650px){#${ID} .ed-control{padding:7px 8px}}
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
  // Cada competência só é considerada quando existe documento com status 'ok'.
  // Consumo por posto pode ser somado entre faturas da mesma competência; demanda
  // medida NÃO é somada entre unidades/medidores diferentes (não é aditiva).
  function validValue(raw) {
    if(raw === null || raw === undefined || raw === '') return null;
    const n=Number(raw);
    return Number.isFinite(n) && n>=0 ? n : null;
  }
  function aggregate(json) {
    const amounts = new Map(), byMonth = new Map();
    const invoices = Array.isArray(json?.faturas) ? json.faturas : [];
    for(const bill of invoices) {
      if(bill?.status !== 'ok' || bill.origem_removida || !isValidMonth(bill.mes_consumo)) continue;
      if(bill.valor_centavos == null) continue;
      const cents = Number(bill.valor_centavos);
      if(!Number.isFinite(cents) || cents < 0) continue;
      const key = bill.mes_consumo;
      amounts.set(key, (amounts.get(key) || 0) + Math.round(cents));
      if(!byMonth.has(key)) byMonth.set(key,[]);
      byMonth.get(key).push(bill);
    }
    if(!amounts.size) return null;
    const latest = [...amounts.keys()].sort().at(-1);
    const lastIdx = monthIndex(latest);
    const entries = Array.from({length:WINDOW_MONTHS},(_,i) => {
      const key = monthKey(lastIdx - WINDOW_MONTHS + 1 + i);
      const rows=byMonth.get(key)||[];
      // Há uma fatura por competência no conjunto atual. Se houver várias,
      // não escolher nem somar picos de demanda sem critério técnico.
      const single=rows.length===1 ? rows[0] : null;
      function sumConsumption(field){
        if(!rows.length)return null;
        const values=rows.map(b=>validValue(b[field]));
        return values.some(v=>v===null) ? null : values.reduce((acc,v)=>acc+v,0);
      }
      return {
        key, cents:amounts.has(key) ? amounts.get(key) : null,
        demand:single ? validValue(single.demanda_medida_kw) : null,
        contracted:single ? validValue(single.demanda_contratada_kw) : null,
        billedDemand:single ? validValue(single.demanda_faturada_kw) : null,
        ponta:sumConsumption('consumo_kwh_ponta'),
        fora:sumConsumption('consumo_kwh_fora_ponta'),
        multipleDemand:rows.length>1
      };
    });
    const present = entries.filter(e => e.cents !== null);
    const total = present.reduce((sum,e) => sum + e.cents,0);
    const average = Math.round(total / present.length);
    const demandValues=entries.map(e=>e.demand).filter(v=>v!==null);
    return {
      entries, latest, count:present.length, total, average,
      averageDemand:demandValues.length ? demandValues.reduce((sum,v)=>sum+v,0)/demandValues.length : null,
      demandCount:demandValues.length,
      consumptionCount:entries.filter(e=>e.ponta!==null && e.fora!==null).length,
      missing:entries.filter(e => e.cents === null),
      missingDemand:entries.filter(e => e.demand === null),
      missingConsumption:entries.filter(e => e.ponta===null || e.fora===null)
    };
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

  // Dois gráficos adicionais compartilham a mesma competência (60 meses) e
  // a mesma origem publicada; o consumo NÃO é derivado do total da fatura.
  function metricScale(data,kind) {
    const numbers=kind==='demand'
      ? data.entries.flatMap(e=>[e.demand,e.contracted])
      : data.entries.flatMap(e=>[e.ponta,e.fora]);
    if(kind==='demand' && data.averageDemand!==null)numbers.push(data.averageDemand);
    const peak=Math.max(0,...numbers.filter(v=>v!==null));
    const base=kind==='demand'?25:5000;
    const step=Math.max(base,Math.ceil(peak/4/base)*base);
    return {step,maximum:step*4};
  }
  function metricAxis(data,kind) {
    const {step,maximum}=metricScale(data,kind);
    const y = value=>PLOT_BOTTOM-(value/maximum)*PLOT_HEIGHT;
    const unit=kind==='demand'?'kW':'kWh';
    const svg=svgNode('svg',{width:77,height:SVG_HEIGHT,viewBox:`0 0 77 ${SVG_HEIGHT}`,role:'presentation','aria-hidden':'true'});
    svg.append(svgNode('text',{x:10,y:30,fill:'#5b5d63','font-size':15},unit));
    for(let i=0;i<=4;i++) {
      const value=i*step;
      const label=kind==='demand'?fmtNumber(value,0):(value===0?'0':`${fmtNumber(value/1000,0)} mil`);
      svg.append(svgNode('text',{x:72,y:y(value)+4,'text-anchor':'end',fill:'#62666b','font-size':13},label));
    }
    return svg;
  }
  function metricFrame(data,kind) {
    const width=MARGIN_LEFT+data.entries.length*MONTH_WIDTH+MARGIN_RIGHT;
    const unit=kind==='demand'?'kW':'kWh';
    const description=kind==='demand'
      ? 'Demanda medida em barras amarelas e linha escura; demanda contratada em linha azul; média da demanda medida tracejada. Valores em kW.'
      : 'Consumo de ponta em barras verdes e consumo fora de ponta em barras vermelhas. Valores em kWh. Não há soma dos postos.';
    const svg=svgNode('svg',{viewBox:`0 0 ${width} ${SVG_HEIGHT}`,width,height:SVG_HEIGHT,role:'img','aria-label':description});
    const {step,maximum}=metricScale(data,kind);
    const y = value=>PLOT_BOTTOM-(value/maximum)*PLOT_HEIGHT;
    svg.append(svgNode('text',{x:18,y:30,fill:'#5b5d63','font-size':15},unit));
    for(let i=0;i<=4;i++) {
      const val=i*step, yy=y(val);
      svg.append(svgNode('line',{x1:MARGIN_LEFT,y1:yy,x2:width-MARGIN_RIGHT,y2:yy,stroke:'#dfe0e2','stroke-width':1.2}));
      const label=kind==='demand'?fmtNumber(val,0):(val===0?'0':`${fmtNumber(val/1000,0)} mil`);
      svg.append(svgNode('text',{x:MARGIN_LEFT-13,y:yy+4,'text-anchor':'end',fill:'#62666b','font-size':13},label));
    }
    const missing=e=>kind==='demand'?e.demand===null:(e.ponta===null || e.fora===null);
    data.entries.forEach((e,i)=>{
      if(!missing(e))return;
      const x=MARGIN_LEFT+i*MONTH_WIDTH;
      svg.append(svgNode('rect',{x:x+5,y:PLOT_TOP,width:MONTH_WIDTH-10,height:PLOT_HEIGHT,fill:'#fff8e8'}));
      svg.append(svgNode('text',{x:x+MONTH_WIDTH/2,y:PLOT_TOP+20,'text-anchor':'middle',fill:'#a06c15','font-size':11},'s/d'));
    });
    function drawLine(valueOf,color,widthPx,opts={}) {
      let segment=[];
      function flush() {
        if(segment.length>=2)svg.append(svgNode('polyline',{
          points:segment.join(' '),fill:'none',stroke:color,'stroke-width':widthPx,
          'stroke-linecap':'round','stroke-linejoin':'round',
          ...(opts.dash?{'stroke-dasharray':opts.dash}:{})
        }));
        segment=[];
      }
      data.entries.forEach((e,i)=>{
        const val=valueOf(e);
        if(val===null || missing(e)){flush();return;}
        segment.push(`${MARGIN_LEFT+i*MONTH_WIDTH+MONTH_WIDTH/2},${y(val)}`);
      });
      flush();
    }
    if(kind==='demand') {
      // Barras amarelas da demanda efetivamente medida.
      data.entries.forEach((e,i)=>{
        if(e.demand===null)return;
        const x=MARGIN_LEFT+i*MONTH_WIDTH+MONTH_WIDTH/2, yy=y(e.demand);
        svg.append(svgNode('rect',{x:x-18,y:yy,width:36,height:PLOT_BOTTOM-yy,rx:2,fill:'#fecb29'}));
      });
      // Linha contratada permite identificar a folga contratual e mudanças de contrato.
      drawLine(e=>e.contracted,CONTRACT,2.5);
      if(data.averageDemand!==null){
        svg.append(svgNode('line',{x1:MARGIN_LEFT,y1:y(data.averageDemand),x2:width-MARGIN_RIGHT,y2:y(data.averageDemand),stroke:'#8c8e93','stroke-width':3,'stroke-dasharray':'10 8'}));
      }
      drawLine(e=>e.demand,'#303744',3.2);
      data.entries.forEach((e,i)=>{
        if(e.demand===null)return;
        const center=MARGIN_LEFT+i*MONTH_WIDTH+MONTH_WIDTH/2, yy=y(e.demand);
        const text=`${fmtFullMonth(e.key)} — demanda medida: ${fmtNumber(e.demand)} kW; contratada: ${e.contracted===null?'não identificada':fmtNumber(e.contracted)+' kW'}; faturada: ${e.billedDemand===null?'não identificada':fmtNumber(e.billedDemand)+' kW'}`;
        const g=svgNode('g',{class:'ed-svg-tooltip',tabindex:0,role:'group','aria-label':text});
        g.append(svgNode('rect',{class:'ed-highlight',x:center-27,y:PLOT_TOP,width:54,height:PLOT_HEIGHT,fill:'transparent'}));
        g.append(svgNode('circle',{cx:center,cy:yy,r:6.8,fill:'#fff',stroke:'#303744','stroke-width':3}));
        g.append(svgNode('text',{x:center,y:Math.max(24,yy-16),'text-anchor':'middle',fill:'#222','font-size':12.5,'font-weight':650},fmtNumber(e.demand,0)));
        g.append(svgNode('title',{},text));svg.append(g);
      });
    } else {
      data.entries.forEach((e,i)=>{
        if(e.ponta===null || e.fora===null)return;
        const center=MARGIN_LEFT+i*MONTH_WIDTH+MONTH_WIDTH/2;
        const label=`${fmtFullMonth(e.key)} — ponta: ${fmtNumber(e.ponta,0)} kWh; fora de ponta: ${fmtNumber(e.fora,0)} kWh`;
        const g=svgNode('g',{class:'ed-svg-tooltip',tabindex:0,role:'group','aria-label':label});
        g.append(svgNode('rect',{class:'ed-highlight',x:center-27,y:PLOT_TOP,width:54,height:PLOT_HEIGHT,fill:'transparent'}));
        [[e.ponta,center-22,GREEN],[e.fora,center+2,RED]].forEach(([value,x,color])=>{
          const yy=y(value);
          g.append(svgNode('rect',{x,y:yy,width:20,height:PLOT_BOTTOM-yy,rx:2,fill:color}));
          g.append(svgNode('text',{x:x+10,y:Math.max(24,yy-8),'text-anchor':'middle',fill:color,'font-size':11.5,'font-weight':700},fmtThousand(value)));
        });
        g.append(svgNode('title',{},label));svg.append(g);
      });
    }
    data.entries.forEach((e,i)=>{
      const center=MARGIN_LEFT+i*MONTH_WIDTH+MONTH_WIDTH/2;
      svg.append(svgNode('text',{x:center,y:PLOT_BOTTOM+29,'text-anchor':'end',transform:`rotate(-45 ${center} ${PLOT_BOTTOM+29})`,fill:missing(e)?'#9f6e1e':'#44474e','font-size':12.5},fmtMonth(e.key)));
    });
    svg.append(svgNode('text',{x:MARGIN_LEFT+data.entries.length*MONTH_WIDTH/2,y:SVG_HEIGHT-10,'text-anchor':'middle',fill:'#53575c','font-size':14},'Mês de consumo (data da leitura)'));
    return svg;
  }
  function showMetric(data,kind){
    const chart=document.querySelector(`#${ID} [data-ed="${kind}-chart"]`);
    if(!chart)return;
    const axis=document.querySelector(`#${ID} [data-ed="${kind}-yaxis"]`);
    const description=document.querySelector(`#${ID} [data-ed="${kind}-subtitle"]`);
    const note=document.querySelector(`#${ID} [data-ed="${kind}-note"]`);
    const count=kind==='demand'?data.demandCount:data.consumptionCount;
    const missing=kind==='demand'?data.missingDemand:data.missingConsumption;
    const unit=kind==='demand'?'kW':'kWh';
    description.textContent=`${fmtFullMonth(data.entries[0].key)} a ${fmtFullMonth(data.latest)} · ${count} de 60 meses com medições de ${unit}.`;
    chart.replaceChildren(metricFrame(data,kind));
    axis.replaceChildren(metricAxis(data,kind));
    const explanations=kind==='demand'
      ? 'Barras e linha: demanda medida. Linha azul: demanda contratada. Linha tracejada: média da demanda medida. Passe o cursor ou selecione cada mês para consultar também a demanda faturada.'
      : 'Cada mês tem duas barras: verde = ponta; vermelha = fora de ponta. Os valores são independentes e não substituem o consumo total publicado pela Copel. Rótulos em mil kWh.';
    note.textContent=explanations+(missing.length?` Sem medições válidas: ${missing.map(e=>fmtMonth(e.key)).join(', ')}.`:'')+' Deslize horizontalmente para ver todo o período.';
    chart.style.scrollBehavior='auto';chart.scrollLeft=chart.scrollWidth;chart.style.scrollBehavior='';
  }

  function show(data) {
    const dashboard=document.getElementById(ID);
    if(!dashboard) return;
    const subtitle=dashboard.querySelector('[data-ed="subtitle"]');
    const frame=dashboard.querySelector('[data-ed="chart"]');
    const yaxis=dashboard.querySelector('[data-ed="yaxis"]');
    const note=dashboard.querySelector('[data-ed="note"]');
    const start=data.entries[0].key;
    subtitle.textContent=`Janela móvel: ${fmtFullMonth(start)} a ${fmtFullMonth(data.latest)} · ${data.count} de 60 meses com fatura validada.`;
    frame.replaceChildren(drawChart(data));
    yaxis.replaceChildren(drawStickyAxis(data));
    showMetric(data,'demand');
    showMetric(data,'consumption');
    const missing=data.missing.map(e=>fmtFullMonth(e.key));
    note.textContent=missing.length
      ? `Média calculada somente sobre os ${data.count} meses com dados. Sem fatura validada: ${missing.join(', ')}. Meses ausentes não foram tratados como R$ 0,00. Deslize horizontalmente para consultar os 5 anos.`
      : `Média calculada sobre os 60 meses com dados. Deslize horizontalmente para consultar os 5 anos.`;
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

  function addMetricSection(parent,kind,title,legendRows){
    const section=node('section','ed-subsection');section.dataset.ed=`${kind}-section`;
    section.append(node('h3','',title));
    const subtitle=node('p','ed-lead','Aguardando dados publicados da Copel.');subtitle.dataset.ed=`${kind}-subtitle`;section.append(subtitle);
    const legend=node('div','ed-legend');
    for(const [symbol,label] of legendRows){
      const key=node('span','ed-key');key.append(node('span',symbol),document.createTextNode(label));legend.append(key);
    }
    section.append(legend);
    const frame=node('div','ed-chart-box');
    const head=node('div','ed-chart-heading');head.append(node('span','',`${kind==='demand'?'kW':'kWh'} · 60 meses · Mês de consumo`));
    const controls=node('div','ed-controls');
    const prev=node('button','ed-control','← 12 meses'),next=node('button','ed-control','12 meses →');
    prev.type='button';next.type='button';
    prev.setAttribute('aria-label',`Voltar 12 meses no gráfico de ${kind==='demand'?'demanda':'consumo'}`);
    next.setAttribute('aria-label',`Avançar 12 meses no gráfico de ${kind==='demand'?'demanda':'consumo'}`);
    controls.append(prev,next);head.append(controls);frame.append(head);
    const area=node('div','ed-plot-area');
    const scroll=node('div','ed-scroller');scroll.dataset.ed=`${kind}-chart`;scroll.tabIndex=0;
    scroll.setAttribute('role','region');scroll.setAttribute('aria-label',`Gráfico mensal de ${kind==='demand'?'demanda':'consumo'} nos últimos 60 meses`);
    const axis=node('div','ed-yaxis');axis.dataset.ed=`${kind}-yaxis`;axis.setAttribute('aria-hidden','true');
    area.append(scroll,axis);frame.append(area);
    const note=node('p','ed-plot-note','Aguardando dados.');note.dataset.ed=`${kind}-note`;frame.append(note);
    section.append(frame);parent.append(section);
    prev.addEventListener('click',()=>scroll.scrollBy({left:-MONTH_WIDTH*12,behavior:'smooth'}));
    next.addEventListener('click',()=>scroll.scrollBy({left:MONTH_WIDTH*12,behavior:'smooth'}));
  }

  function mount() {
    const panel=document.getElementById('energy');
    if(!panel || document.getElementById(ID))return;
    const style=node('style');style.textContent=css;document.head.append(style);
    const section=node('section');section.id=ID;section.dataset.version='1.2';
    const heading=node('h3','','Valor mensal das faturas de energia elétrica');section.append(heading);
    const subtitle=node('p','ed-lead','Exibindo as 60 competências mais recentes disponíveis.');subtitle.dataset.ed='subtitle';section.append(subtitle);
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
    addMetricSection(section,'demand','Demanda elétrica mensal',[
      ['ed-key-bar','Demanda medida (barras)'],['ed-key-line','Demanda medida (linha)'],
      ['ed-key-contract','Demanda contratada'],['ed-key-average','Média da demanda medida']
    ]);
    addMetricSection(section,'consumption','Consumo mensal de energia elétrica — ponta e fora de ponta',[
      ['ed-key-green','Consumo na ponta (kWh)'],['ed-key-red','Consumo fora de ponta (kWh)']
    ]);
    const err=node('p','ed-error');err.dataset.ed='error';err.hidden=true;section.append(err);
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
