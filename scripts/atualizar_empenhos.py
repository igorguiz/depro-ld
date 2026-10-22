#!/usr/bin/env python3
"""Leitura somente de PDFs públicos SEI (ARCOLON). Não estima liquidações a partir de pagamentos.

Apenas publica NE validada e vínculos documentais. Não publica saldo não comprovado.
"""
import html, json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import fitz
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data'/'empenhos.json'
SOURCE='https://sei.utfpr.edu.br/sei/modulos/pesquisa/md_pesq_processo_exibir.php?iI3OtHvPArITY997V09rhsSkbDKbaYSycOHqqF2xsM0IaDkkEyJpus7kCPb435VNEAb16AAxmJKUdrsNWVIqQ81On4VzSUQQ8RvYnANh-v1u95GlOXhULO7esemKdXq0'
DOC_PATH='/sei/modulos/pesquisa/md_pesq_documento_consulta_externa.php'
LINK_RE=re.compile(r'(?:https?://sei\.utfpr\.edu\.br)?(?:/sei/modulos/pesquisa/)?md_pesq_documento_consulta_externa\.php\?[\w=&;%.-]+',re.I)
MONEY=re.compile(r'(?<!\d)(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})(?!\d)')
EXPECTED='2026NE000051'

def cents(value):
    x=value.replace('.','').replace(',','.')
    return int(round(float(x)*100))

def br(v):
    return f'{v/100:,.2f}'.replace(',','X').replace('.',',').replace('X','.')

def textnorm(s): return re.sub(r'\s+',' ',s or '').strip()

def discover(markup):
    soup=BeautifulSoup(markup,'html.parser'); found=[]
    for tr in soup.find_all('tr'):
        plain=textnorm(tr.get_text(' ',strip=True)); low=plain.casefold()
        if not ('nota de empenho' in low or 'informa' in low and 'pagamento' in low): continue
        m=re.search(r'\b(\d{6,8})\b',plain)
        if not m: continue
        url=None
        for tag in tr.find_all(True):
            for attr in ('onclick','href','data-url'):
                s=tag.get(attr)
                if not isinstance(s,str): continue
                found_link=LINK_RE.search(html.unescape(s).replace('\\/','/'))
                if not found_link: continue
                u=urljoin(SOURCE,found_link.group(0)); p=urlparse(u)
                if p.scheme=='https' and p.hostname=='sei.utfpr.edu.br' and p.path==DOC_PATH and p.query:
                    url=u;break
            if url:break
        if url:found.append({'sei':m.group(1),'rotulo':plain[:260],'url':url,'tipo':'ne' if 'nota de empenho' in low else 'pagamento'})
    return list({d['sei']:d for d in found}.values())

def fetch(session,url,accept_pdf=False):
    for i,timeout in enumerate((20,40,70),1):
        try:
            r=session.get(url,timeout=(10,timeout));r.raise_for_status()
            if accept_pdf:
                if not r.content.startswith(b'%PDF-'): raise ValueError('Documento não é PDF')
            else:
                if 'html' not in r.headers.get('Content-Type','').lower(): raise ValueError('Processo não retornou HTML')
            return r
        except (requests.Timeout,requests.ConnectionError):
            if i==3:raise
            time.sleep(i*2)
    raise RuntimeError('Sem resposta')

def extract_pdf(blob):
    doc=fitz.open(stream=blob,filetype='pdf')
    if doc.page_count>15:raise ValueError('PDF acima do limite de páginas')
    s='\n'.join(page.get_text(sort=True) for page in doc)
    if len(s.strip())<70:raise ValueError('PDF sem texto extraível')
    return s

def parse_ne(t):
    norm=textnorm(t)
    if not re.search(r'Nota de Empenho',norm,re.I):return None
    if not ('82.395.773/0001-89' in t and '150148' in t):return None
    # Versão da NE usada: deve conter UG 150148, ano 2026, NE 51 e favorecido.
    if not re.search(r'2026\s+NE\s+0*51\b',norm,re.I):return None
    m=re.search(r'\bData\s+de\s+Emiss[aã]o\b.*?\bValor\b\s*\n\s*\d\d/\d\d/\d{4}[^\n]*?\b([\d.]+,\d{2})\s*$',t,re.I|re.M|re.S)
    # Fonte mais robusta: operações contidas na seção Lista de Itens.
    sec=re.search(r'Lista de Itens(.*?)(?:Assinaturas|\Z)',t,re.I|re.S)
    if not sec:return None
    ops=[]
    for line in sec.group(1).splitlines():
        line=textnorm(line)
        mm=re.search(r'^(\d\d/\d\d/\d{4})\s+(Inclus[aã]o|Refor[cç]o|Anula[cç][aã]o|Cancelamento|Redu[cç][aã]o)\b.*?([\d.]+,\d{2})\s*$',line,re.I)
        if mm:
            op=mm.group(2).casefold();signed=-1 if any(x in op for x in ('anula','cancel','redu')) else 1
            ops.append({'data':mm.group(1),'operacao':mm.group(2),'valor_centavos':signed*cents(mm.group(3))})
    if not ops:return None
    total=sum(p['valor_centavos'] for p in ops)
    if total<0:return None
    # Confere contra Total da Lista do documento, se presente; falhas rejeitam.
    mt=re.search(r'Total da Lista\s*\n\s*([\d.]+,\d{2})',sec.group(1),re.I)
    if mt and abs(total-cents(mt.group(1)))>1:raise ValueError('Movimentações não fecham com Total da Lista')
    version=re.search(r'Vers[aã]o\s+Data/Hora.*?\n\s*(\d{3})\s+(\d\d/\d\d/\d{4})',t,re.I|re.S)
    return {'numero':EXPECTED,'valor_total_centavos':total,'movimentacoes':ops,'versao':int(version.group(1)) if version else None,'data_versao':version.group(2) if version else None}

def parse_payment(t):
    if not re.search(r'INFORMA[CÇ][OÕ]ES SOBRE O PAGAMENTO',t,re.I):return None
    normalized=textnorm(t)
    em=re.search(r'150148\s*/\s*(2026NE0*51)\b',normalized,re.I)
    if not em:return None
    nf=re.findall(r'Nota Fiscal\s*(\d{1,6})\s*:\s*Ref\.\s*(?:a\s*)?(Servi[cç]os|Materiais)',normalized,re.I)
    ob=re.search(r'150148\s*/\s*(2026OB\d{6})',normalized,re.I)
    dr=re.search(r'150148\s*/\s*(2026DR\d{6})\s*[-–]\s*([\d.]+,\d{2})',normalized,re.I)
    op=re.search(r'150148\s*/\s*(2026OP\d{6})\s*[-–]\s*([\d.]+,\d{2})',normalized,re.I)
    return {'empenho':EXPECTED,'notas':[{'numero':n,'natureza':type_} for n,type_ in nf], 'ordem_bancaria':ob.group(1) if ob else None,'documento_retencao':dr.group(1) if dr else None,'retencao_centavos':cents(dr.group(2)) if dr else None,'ordem_pagamento':op.group(1) if op else None,'ordem_pagamento_centavos':cents(op.group(2)) if op else None}

def parse_any_payment(t):
    if not re.search(r'INFORMA[CÇ][OÕ]ES SOBRE O PAGAMENTO',t,re.I): return None
    n=textnorm(t)
    ne=re.search(r'150148\s*/\s*((?:202[0-9])NE\d{6})\b',n,re.I)
    if not ne:return None
    item=parse_payment(t) if ne.group(1).upper()==EXPECTED else None
    if item:return item
    nf=re.findall(r'Nota Fiscal\s*(\d{1,6})\s*:\s*Ref\.\s*(?:a\s*)?(Servi[cç]os|Materiais)',n,re.I)
    ob=re.search(r'150148\s*/\s*(2026OB\d{6})',n,re.I)
    dr=re.search(r'150148\s*/\s*(2026DR\d{6})\s*[-–]\s*([\d.]+,\d{2})',n,re.I)
    op=re.search(r'150148\s*/\s*(2026OP\d{6})\s*[-–]\s*([\d.]+,\d{2})',n,re.I)
    return {'empenho':ne.group(1).upper(),'notas':[{'numero':x,'natureza':y} for x,y in nf],
       'ordem_bancaria':ob.group(1) if ob else None,
       'documento_retencao':dr.group(1) if dr else None,
       'retencao_centavos':cents(dr.group(2)) if dr else None,
       'ordem_pagamento':op.group(1) if op else None,
       'ordem_pagamento_centavos':cents(op.group(2)) if op else None}

def parse_any_ne(t):
    n=textnorm(t)
    if 'Nota de Empenho' not in n or '150148' not in n or '82.395.773/0001-89' not in n:return None
    m=re.search(r'\b(202[0-9])\s+NE\s+(\d{1,6})\b',n,re.I)
    if not m:return None
    number=m.group(1)+'NE'+m.group(2).zfill(6)
    if number==EXPECTED:return parse_ne(t)
    sec=re.search(r'Lista de Itens(.*?)(?:Assinaturas|\Z)',t,re.I|re.S)
    if not sec:return None
    operations=[]
    for line in sec.group(1).splitlines():
        mm=re.search(r'^(\d\d/\d\d/\d{4})\s+(Inclus[aã]o|Refor[cç]o|Anula[cç][aã]o|Cancelamento|Redu[cç][aã]o)\b.*?([\d.]+,\d{2})\s*$',textnorm(line),re.I)
        if mm:
            sign=-1 if any(k in mm.group(2).lower() for k in ('anula','cancel','redu')) else 1
            operations.append({'data':mm.group(1),'operacao':mm.group(2),'valor_centavos':sign*cents(mm.group(3))})
    if not operations:return None
    total=sum(v['valor_centavos'] for v in operations)
    version=re.search(r'Vers[aã]o\s+Data/Hora.*?\n\s*(\d{3})\s+(\d\d/\d\d/\d{4})',t,re.I|re.S)
    return {'numero':number,'valor_total_centavos':total,'movimentacoes':operations,
       'versao':int(version.group(1)) if version else None,
       'data_versao':version.group(2) if version else None}

def run():
    sess=requests.Session();sess.headers.update({'User-Agent':'Mozilla/5.0','Accept-Language':'pt-BR,pt;q=0.9'})
    page=fetch(sess,SOURCE); docs=discover(page.text)
    print('Documentos financeiros com link público:',len(docs),flush=True)
    candidates=[];payments=[];errors=[]
    for d in docs[:240]:
        try:
            text=extract_pdf(fetch(sess,d['url'],True).content)
            if d['tipo']=='ne':
                ne=parse_any_ne(text)
                if ne:ne.update({'sei':d['sei'],'url':d['url']});candidates.append(ne)
            else:
                item=parse_any_payment(text)
                if item:item.update({'sei':d['sei'],'url':d['url']});payments.append(item)
        except Exception as exc:errors.append({'sei':d['sei'],'erro':str(exc)[:140]})
    by_number={}
    for ne in candidates:
        key=ne['numero'];old=by_number.get(key)
        if not old or (ne.get('versao') or 0,ne.get('data_versao') or '')>(old.get('versao') or 0,old.get('data_versao') or ''):by_number[key]=ne
    if EXPECTED not in by_number:raise ValueError('NE 2026NE000051 não localizada: dados anteriores preservados')
    nums=set(by_number)|{x['empenho'] for x in payments}
    empenhos=[]
    for number in sorted(nums,reverse=True):
        ne=by_number.get(number);atual=number.startswith('2026')
        empenhos.append({'numero':number,'ug':'150148','exercicio':int(number[:4]),
          'valor_total_centavos':ne['valor_total_centavos'] if ne and atual else None,
          'versao':ne['versao'] if ne else None,'data_versao':ne['data_versao'] if ne else None,
          'sei':ne['sei'] if ne else None,'url':ne['url'] if ne else None,
          'movimentacoes':ne['movimentacoes'] if ne else [],
          'saldo_a_liquidar_centavos':None,'situacao_saldo':'A apurar: faltam liquidações e estornos validados',
          'pagamentos_documentados':sum(x['empenho']==number for x in payments)})
    payload={'schema_version':2,'atualizado_em':datetime.now(timezone.utc).isoformat(timespec='seconds'),
      'processo_financeiro':'23064.037514/2022-95','contrato_id':'arcolon',
      'empenhos':empenhos,'documentos_pagamento':list({x['sei']:x for x in payments}.values()),
      'diagnostico':{'documentos_listados':len(docs),'notas_empenho_reconhecidas':len(candidates),
       'documentos_pagamento_reconhecidos':len(payments),'erros_leitura':errors[:40],
       'aviso':'Saldo contábil não é dedutível apenas de documentos de pagamentos.'}}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(OUT)
    print('Empenhos identificados:',', '.join(sorted(nums)), 'pagamentos:',len(payments))
    print('NE 2026NE000051:',br(by_number[EXPECTED]['valor_total_centavos']),'— saldo a apurar')

if __name__=='__main__':
    try:run()
    except Exception as e:print('ERRO: dados anteriores preservados:',e,file=sys.stderr);sys.exit(1)
