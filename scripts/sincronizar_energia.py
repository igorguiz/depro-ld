#!/usr/bin/env python3
"""Sincroniza faturas Copel em compartilhamento Nextcloud (somente leitura).

Uso no GitHub Actions: NEXTCLOUD_SHARE_TOKEN, NEXTCLOUD_SHARE_PASSWORD,
NUVEM_BASE_URL (opcional), ENERGIA_ID_CHAVE (opcional, mas recomendada).

Nao publica PDFs, nomes de arquivos, URLs, numeros de UC, CPF/CNPJ,
enderecos, nem credenciais. A saida JSON e PUBLICA no GitHub Pages.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit
from xml.etree import ElementTree as ET

import pymupdf as fitz
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
DATA_FILE = DATA / 'energia.json'
STATE_FILE = DATA / 'energia_estado.json'
STATUS_FILE = DATA / 'energia_status.json'
DEFAULT_URL = 'https://nuvem.utfpr.edu.br'
NS = {'d': 'DAV:'}
MAX_FOLDERS = 300
MAX_FILES = 3000
MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_XML_BYTES = 3 * 1024 * 1024
HEADERS = {'X-Requested-With': 'XMLHttpRequest'}
PARSER_VERSION = 'copel-multiformato-4'


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def read_json(path, fallback):
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return fallback


def save_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temp.replace(path)


def parse_money(raw):
    """Valores monetarios em reais => centavos, sem arredondar ponto flutuante."""
    if raw is None:
        return None
    s = re.sub(r'[^\d,.\-]', '', str(raw))
    if not s:
        return None
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    elif '.' in s and len(s.rsplit('.', 1)[-1]) == 3:
        s = s.replace('.', '')
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
    try:
        return int((Decimal(s) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return None


def parse_decimal(raw):
    try:
        s = re.sub(r'[^\d,.-]', '', str(raw))
        if ',' in s:
            s = s.replace('.', '').replace(',', '.')
        elif re.fullmatch(r'-?\d{1,3}(?:\.\d{3})+', s):
            s = s.replace('.', '')
        return float(s)
    except (ValueError, TypeError):
        return None


def find_after_label(text, expressions, number_pattern):
    for expr in expressions:
        m = re.search(expr + r'\s*[:\-–]?\s*(?:R\$\s*)?(' + number_pattern + r')', text, re.I)
        if m:
            return m.group(1)
    return None


def parse_invoice_text(text):
    """Campos conferíveis do DANF3E / extrato tarifário da Copel.

    Usa os títulos presentes no próprio documento. Valores de energia injetada,
    tarifas e histórico de outros meses nunca substituem consumo ou valor atual.
    """
    number = r'(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?'
    money = r'-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}'
    month = find_after_label(text, [
        r'(?<!\w)M[eê]s\s*/\s*Ano\s+Consumo\s*/\s*Uso\s+do\s+Sistema',
        r'(?<!\w)M[eê]s\s+de\s+refer[eê]ncia',
        r'(?<!\w)Refer[eê]ncia(?:\s+de\s+faturamento)?',
        r'(?<!\w)Compet[eê]ncia',
        r'(?<!\w)M[eê]s\s*/\s*Ano',
    ], r'(?:0?[1-9]|1[0-2])\s*/\s*20\d{2}|20\d{2}\s*[-/]\s*(?:0?[1-9]|1[0-2])')
    comp = None
    if month:
        match = re.match(r'(\d{1,2})\s*/\s*(20\d{2})', month)
        if match:
            comp = f'{match.group(2)}-{int(match.group(1)):02d}'
        else:
            match = re.match(r'(20\d{2})\s*[-/]\s*(\d{1,2})', month)
            if match:
                comp = f'{match.group(1)}-{int(match.group(2)):02d}'

    # Fatura DANF3E: na primeira página, a referência, o vencimento e o total
    # aparecem juntos; na página de continuação há também uma linha TOTAL.
    amount = find_after_label(text, [
        r'(?<!\w)TOTAL\s+A\s+PAGAR',
        r'(?<!\w)VALOR\s+TOTAL\s+DA\s+FATURA',
        r'(?<!\w)VALOR\s+DA\s+FATURA',
        r'(?<!\w)TOTAL\s+DA\s+FATURA',
        r'(?<!\w)VALOR\s+A\s+PAGAR',
    ], money)
    if amount is None and comp:
        ref = f'{int(comp[5:]):02d}/{comp[:4]}'
        # Evita capturar valores de impostos e meses anteriores do histórico.
        match = re.search(r'(?m)^\s*'+re.escape(ref)+r'\s+\d{2}/\d{2}/20\d{2}\s+R\$\s*('+money+r')', text)
        if match:
            amount = match.group(1)
    if amount is None:
        match = re.search(r'(?m)^\s*TOTAL\s{2,}('+money+r')(?=\s|$)', text)
        if match:
            amount = match.group(1)

    # Fatura Copel antiga: total monetário em linha isolada do cabeçalho.
    # Só utiliza o valor com prefixo R$; não usa montantes de tributos.
    if amount is None:
        match = re.search(r'(?m)^.{0,180}\b\d{2}/\d{2}/20\d{2}\s+R\$\s*('+money+r')(?=\s|$)', text)
        if match:
            amount = match.group(1)

    # O extrato da Copel contém um item específico "ENERGIA ELETRICA CONSUMO"
    # com leitura anterior, leitura atual e medição. Isso evita somar TE+TUSD
    # (mesmo kWh faturado duas vezes) e evita confundir injeção solar com carga.
    consumption = find_after_label(text, [
        r'(?<!\w)CONSUMO\s+TOTAL\s*(?:\(\s*kWh\s*\)|em\s+kWh)',
        r'(?<!\w)CONSUMO\s*(?:\(\s*kWh\s*\)|EM\s+kWh|kWh)',
        r'(?<!\w)ENERGIA\s+CONSUMIDA\s*(?:\(\s*kWh\s*\)|kWh)',
    ], number)
    # A regra genérica acima só é usada se rotulada com o valor diretamente;
    # "CONSUMO kWh PT [leituras...]" não é um valor direto.
    match_total = re.search(r'(?m)^\s*ENERGIA\s+ELETRICA\s+CONSUMO\s+\d+\s+\d+\s+('+number+r')(?=\s|$)', text, re.I)
    if match_total:
        consumption = match_total.group(1)
    else:
        # Algumas faturas trazem apenas os itens TE em ponta e fora de ponta.
        # Cada item aparece também como USD/TUSD: nunca somar os dois.
        p = re.search(r'(?m)^\s*ENERGIA\s+ELETRICA\s+TE\s+PONTA\s+(?:kWh\s+)?('+number+r')(?=\s|$)', text, re.I)
        fp = re.search(r'(?m)^\s*ENERGIA\s+ELETRICA\s+TE\s+F\s*PONTA\s+(?:kWh\s+)?('+number+r')(?=\s|$)', text, re.I)
        if p and fp:
            a, b = parse_decimal(p.group(1)), parse_decimal(fp.group(1))
            if a is not None and b is not None:
                consumption = str(a+b).replace('.', ',') if (a+b)%1 else str(int(a+b))

    demand = find_after_label(text, [
        r'(?<!\w)DEMANDA\s+MEDIDA\s*(?:\(\s*kW\s*\)|kW)?',
        r'(?<!\w)DEMANDA\s+REGISTRADA\s*(?:\(\s*kW\s*\)|kW)?',
    ], number)
    contracted = find_after_label(text, [
        r'(?<!\w)Demanda\s+Todos\s+os\s+Per[ií]odos',
    ], number)
    # Linha do extrato detalhado: anterior, atual, medido, contratado,
    # faturado, tarifa e total. "DEMANDA USD ISENTA ICMS" NÃO é demanda medida.
    demand_line = re.search(r'(?m)^\s*DEMANDA\s+USD\s+\d+\s+\d+\s+('+number+r')\s+('+number+r')\s+('+number+r')\s+', text, re.I)
    if demand_line:
        demand = demand_line.group(1)
        contracted = contracted or demand_line.group(2)

    # Extrato antigo Copel: DEMANDA (sem USD), leituras anterior e atual,
    # valores medido, contratado e faturado, nesta ordem.
    legacy_demand = re.search(
        r'(?m)^\s*DEMANDA\s+(?!ISENTA|USD)\d+\s+\d+\s+'
        r'('+number+r')\s+('+number+r')\s+('+number+r')(?=\s|$)', text, re.I)
    if legacy_demand:
        demand = legacy_demand.group(1)
        contracted = contracted or legacy_demand.group(2)

    injected = None
    injection_line = re.search(r'(?m)^\s*ENERGIA\s+GERADA\s*/\s*INJETADA\s+FORA\s+P\s+\d+\s+\d+\s+('+number+r')(?=\s|$)', text, re.I)
    if injection_line:
        injected = parse_decimal(injection_line.group(1))

    uc = find_after_label(text, [
        r'(?<!\w)UNIDADE\s+CONSUMIDORA\s*(?:N[º°o.]*)?',
        r'(?<!\w)N[º°o.]*\s+DA\s+UC',
        r'(?<!\w)INSTALA[CÇ][AÃ]O\s*N[º°o.]*',
    ], r'\d[\d.\-]{4,20}')
    if not uc and comp:
        ref = f'{int(comp[5:]):02d}/{comp[:4]}'
        # DANF3E: terceira página inclui UC + referência + vencimento + total.
        match = re.search(r'(?m)^\s*(\d{12,16})\s+'+re.escape(ref)+r'\s+\d{2}/\d{2}/20\d{2}\s+R\$', text)
        if match:
            uc = match.group(1)
    value = parse_money(amount)
    kwh = parse_decimal(consumption)
    kw = parse_decimal(demand)
    contracted_kw = parse_decimal(contracted)
    problems = []
    if comp is None:
        problems.append('competência não identificada')
    if value is None or value < 0:
        problems.append('valor total não identificado')
    if kwh is None or kwh < 0:
        problems.append('consumo em kWh não identificado')
    if kwh is not None and kwh > 100000000:
        problems.append('consumo fora do intervalo esperado')
    return {
        'status': 'conferencia' if problems else 'ok',
        'motivo': '; '.join(problems) if problems else None,
        'competencia': comp,
        'valor_centavos': value if value is not None and value >= 0 else None,
        'consumo_kwh': kwh if kwh is not None and kwh >= 0 else None,
        'demanda_medida_kw': kw if kw is not None and kw >= 0 else None,
        'demanda_contratada_kw': contracted_kw if contracted_kw is not None and contracted_kw >= 0 else None,
        'energia_injetada_kwh': injected if injected is not None and injected >= 0 else None,
        '_uc': re.sub(r'\D', '', uc) if uc else None,
    }



def br_money_float(raw):
    v = parse_money(raw)
    return None if v is None else round(v / 100, 2)


def extract_detailed_bill(pdf_bytes):
    """Completa a extração clássica; usa principalmente o extrato de faturamento,
    sem duplicar quantidades em linhas TE/TUSD ou créditos de energia.
    """
    with fitz.open(stream=pdf_bytes, filetype='pdf') as doc:
        text = '\n'.join(page.get_text(sort=True) for page in doc)
    base = parse_invoice_text(text)
    fields = dict(base)
    fields['tipo_documento'] = 'fatura_individual'
    fields['competencia_copel'] = base.get('competencia')
    # Leituras são datas vinculadas aos rótulos específicos da tabela técnica.
    previous = re.search(r'Data Real Leit Anterior\s+(\d{2}/\d{2}/\d{4})', text, re.I)
    current = re.search(r'Data Real Leit Atual\s+(\d{2}/\d{2}/\d{4})', text, re.I)
    if not previous or not current:
        # DANF3E cabeçalho: anterior / atual / número de dias / próxima leitura
        lead = re.search(r'(?m)^.*?(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+\d{1,3}\s+\d{2}/\d{2}/\d{4}', text)
        if lead:
            previous = previous or lead.group(1)
            current = current or lead.group(2)
    def datefmt(match):
        if match is None: return None
        d = match.group(1) if hasattr(match,'group') else match
        try: return datetime.strptime(d,'%d/%m/%Y').date().isoformat()
        except ValueError: return None
    fields['leitura_anterior'] = datefmt(previous)
    fields['leitura_atual'] = datefmt(current)
    fields['mes_consumo'] = (fields['leitura_atual'] or '')[:7] or base.get('competencia')
    if fields['leitura_atual'] and fields['leitura_anterior'] and fields['leitura_anterior'] >= fields['leitura_atual']:
        fields['status'] = 'conferencia'
        fields['motivo'] = 'Datas de leitura inconsistentes'
    # Extrato com leituras; identificar postos pelos rótulos TE, ou modelo antigo ELET.
    numeric = r'[-]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?'
    for suffix, labels in {
        'ponta': [r'ENERGIA ELETRICA TE PONTA',r'ENERGIA ELET CONSUMO PTA'],
        'fora_ponta': [r'ENERGIA ELETRICA TE F\s*PONTA',r'ENERGIA ELET CONSUMO F PTA'],
    }.items():
        value = None
        for label in labels:
            # Primeira página: 'kWh quantidade preço unitário valor';
            # páginas de extrato podem trazer leituras antes da quantidade.
            m = re.search(r'(?m)^\s*'+label+r'\s+(?:kWh\s+)?('+numeric+r')\s+('+numeric+r')\s+('+numeric+r')(?:\s+('+numeric+r'))?',text,re.I)
            if m:
                vals = [parse_decimal(x) for x in m.groups() if x is not None]
                # Se o segundo campo é preço de seis casas, primeiro é quantidade.
                if len(vals)>=3 and vals[1] is not None and vals[1] < 10 and ',' in m.group(2):
                    value=vals[0]
                elif len(vals)>=3 and vals[0] >= 100 and vals[1] >= 100:
                    value=vals[2]
                elif len(vals)>=3:
                    value=vals[0]
                break
        fields['consumo_kwh_'+suffix] = value
    p1=fields['consumo_kwh_ponta'];p2=fields['consumo_kwh_fora_ponta']
    if p1 is not None and p2 is not None:
        total=p1+p2
        if base.get('consumo_kwh') is not None and abs(total-base['consumo_kwh'])>1.01:
            fields['status']='conferencia';fields['motivo']='Consumos por posto divergem do total medido'
        fields['consumo_kwh']=base['consumo_kwh'] if base.get('consumo_kwh') is not None else total
    # Medição DANF3E, ou medição legada na linha do extrato.
    # Linhas DA DEMANDA USD podem ter 400kW faturado e 227kW medido.
    m = re.search(r'(?m)^\s*DEMANDA\s+(?:USD\s+)?(?!ISENTA)(\d+)\s+(\d+)\s+('+numeric+r')\s+('+numeric+r')\s+('+numeric+r')',text,re.I)
    if m:
        fields['demanda_medida_kw']=parse_decimal(m.group(3))
        fields['demanda_contratada_kw']=parse_decimal(m.group(4))
        fields['demanda_faturada_kw']=parse_decimal(m.group(5))
    else:
        fields['demanda_faturada_kw']=None
    with fitz.open(stream=pdf_bytes,filetype='pdf') as doc:
        extrato=doc[-1].get_text(sort=True)
    # Injeção: preferir linha de medição 'ENERGIA GERADA/INJETADA'.
    # NÃO somar linhas TE + TUSD, pois são as mesmas quantidades de créditos.
    for key,position in [('ponta','PONTA'),('fora_ponta',r'FORA\s+P')]:
        mm=re.search(r'ENERGIA GERADA/INJETADA\s+'+position+r'\s+\d+\s+\d+\s+('+numeric+r')(?=\s|$)',extrato,re.I)
        fields['energia_injetada_kwh_'+key]=parse_decimal(mm.group(1)) if mm else None
    # Preços e montantes saem do extrato individual na última página,
    # cujas colunas Medido/Faturado/Tarifa/Total estão alinhadas.
    line_patterns={
        'te_ponta':r'ENERGIA ELETRICA TE PONTA',
        'tusd_ponta':r'ENERGIA ELETRICA (?:USD|TUSD) PONTA',
        'te_fora_ponta':r'ENERGIA ELETRICA TE F\s*PONTA',
        'tusd_fora_ponta':r'ENERGIA ELETRICA (?:USD|TUSD) F\s*PONTA'
    }
    for key,label in line_patterns.items():
        match=re.search(r'(?m)^\s*'+label+r'\s+(\d+)\s+(\d+)\s+('+numeric+r')\s+('+numeric+r')\s+('+numeric+r')\s+('+numeric+r')',extrato,re.I)
        fields['preco_faturado_'+key]=parse_decimal(match.group(5)) if match else None
        fields['valor_'+key+'_reais']=br_money_float(match.group(6)) if match else None
        fields['tarifa_'+key]=None
    section=extrato[extrato.find('Informações Suplementares'):] if 'Informações Suplementares' in extrato else ''
    for label,postfix in [('CONSUMO F PONTA','fora_ponta'),('CONSUMO PTA','ponta')]:
        m=re.search(r'(?m)^\s*'+label+r'\s+('+numeric+r')(?:\s+('+numeric+r'))?',section,re.I)
        if m and m.group(2):
            fields['tarifa_tusd_'+postfix]=parse_decimal(m.group(1))
            fields['tarifa_te_'+postfix]=parse_decimal(m.group(2))
    for prefix in ('tarifa','preco_faturado'):
        for postfix in ('ponta','fora_ponta'):
            te=fields.get(prefix+'_te_'+postfix);tusd=fields.get(prefix+'_tusd_'+postfix)
            fields[prefix+'_total_'+postfix] = round(te+tusd,6) if te is not None and tusd is not None else None
    injected=[fields['energia_injetada_kwh_ponta'],fields['energia_injetada_kwh_fora_ponta']]
    fields['energia_injetada_kwh']=sum(x for x in injected if x is not None) if any(x is not None for x in injected) else base.get('energia_injetada_kwh')
    fields['valor_reais']=round(fields['valor_centavos']/100,2) if fields.get('valor_centavos') is not None else None
    fields['validacao_campos']={k:('identificado' if fields.get(k) is not None else 'indisponivel') for k in
        ['consumo_kwh_ponta','consumo_kwh_fora_ponta','demanda_medida_kw','demanda_contratada_kw','energia_injetada_kwh_fora_ponta','tarifa_te_ponta','tarifa_tusd_ponta','tarifa_te_fora_ponta','tarifa_tusd_fora_ponta']}
    return fields


def parse_historical_pdf(pdf_bytes):
    """Histórico Copel CMEHFAT0: 3 referências por página, texto lateral.
    Os blocos são lidos por coordenadas de texto vetorial, não por OCR.
    Retorna registros independentes por mês, com tarifas e leituras desconhecidas.
    """
    results=[]
    with fitz.open(stream=pdf_bytes,filetype='pdf') as doc:
        for page in doc:
            words=page.get_text('words')
            dates=sorted([w for w in words if re.fullmatch(r'(?:0[1-9]|1[0-2])/20\d{2}',w[4]) and 140<w[0]<500 and w[1]>720],key=lambda w:w[0])
            for w in dates:
                ref=w[4]; x=w[0]
                def at(dx, y, tolerance=16):
                    candidates=[z for z in words if abs(z[0]-(x+dx))<tolerance and abs((z[1]+z[3])/2-y)<20 and re.fullmatch(r'[\d,.]+',z[4])]
                    return min(candidates,key=lambda z:abs(z[0]-(x+dx))+abs((z[1]+z[3])/2-y)) [4] if candidates else None
                # coordenadas fixas do formulário CMEHFAT0 (colunas deslocadas 121,92 pt)
                p=at(15,665); fp=at(15,617); demand=at(75,566); contract=at(74,82); total=at(91,71)
                # total monetário fica perto de x+91, y=70; medida no bloco em x+75.
                k1=parse_decimal(p); k2=parse_decimal(fp); d=parse_decimal(demand); c=parse_decimal(contract)
                v=int(round(float(total.replace(',',''))*100)) if total and re.fullmatch(r'[\d,]+\.\d{2}',total) else None
                problems=[]
                if k1 is None or k2 is None: problems.append('consumo por posto não identificado')
                if v is None: problems.append('total da fatura não identificado')
                if d is None: problems.append('demanda medida não identificada')
                if c is None: problems.append('demanda contratada não identificada')
                period=ref[3:]+'-'+ref[:2]
                record={'tipo_documento':'historico_faturamento','competencia':period,'competencia_copel':period,'mes_consumo':period,
                    'leitura_anterior':None,'leitura_atual':None,'consumo_kwh_ponta':k1,'consumo_kwh_fora_ponta':k2,
                    'consumo_kwh':(k1+k2 if k1 is not None and k2 is not None else None),
                    'demanda_medida_kw':d,'demanda_contratada_kw':c,'demanda_faturada_kw':None,
                    'energia_injetada_kwh_ponta':None,'energia_injetada_kwh_fora_ponta':None,'energia_injetada_kwh':None,
                    'valor_centavos':v,'valor_reais':round(v/100,2) if v is not None else None,
                    'status':'conferencia' if problems else 'parcial','motivo':'; '.join(problems) if problems else 'Histórico sem tarifas TE/TUSD e datas exatas de leitura',
                    '_uc':None}
                for prefix in ('tarifa','preco_faturado'):
                    for key in ('te_ponta','tusd_ponta','te_fora_ponta','tusd_fora_ponta','total_ponta','total_fora_ponta'):
                        record[prefix+'_'+key]=None
                for key in ('te_ponta','tusd_ponta','te_fora_ponta','tusd_fora_ponta'):
                    record['valor_'+key+'_reais']=None
                record['validacao_campos']={'consumo_kwh_ponta':'identificado' if k1 is not None else 'indisponivel',
                    'consumo_kwh_fora_ponta':'identificado' if k2 is not None else 'indisponivel',
                    'valor_reais':'identificado' if v is not None else 'indisponivel'}
                results.append(record)
    return results


def parse_pdf_records(pdf_bytes):
    try:
        with fitz.open(stream=pdf_bytes,filetype='pdf') as doc:
            if doc.is_encrypted: return [{'status':'conferencia','motivo':'PDF protegido por senha'}]
            prefix='\n'.join(page.get_text(sort=False)[:1500] for page in doc)
        if 'CMEHFAT0' in prefix or 'Histórico de Faturamento' in prefix:
            records=parse_historical_pdf(pdf_bytes)
            return records or [{'status':'conferencia','motivo':'Nenhum mês identificado no histórico'}]
        return [extract_detailed_bill(pdf_bytes)]
    except Exception:
        return [{'status':'conferencia','motivo':'PDF não interpretável'}]


def parse_pdf_invoice(pdf_bytes):
    """Extrai texto do PDF; não tenta OCR e nunca estima valores ausentes."""
    try:
        with fitz.open(stream=pdf_bytes, filetype='pdf') as doc:
            if doc.is_encrypted:
                return {'status': 'conferencia', 'motivo': 'PDF protegido por senha'}
            text = '\n'.join(page.get_text(sort=True) for page in (doc[i] for i in range(min(len(doc), 8))))
    except Exception:
        return {'status': 'conferencia', 'motivo': 'PDF inválido ou ilegível'}
    if len(text.strip()) < 55:
        return {'status': 'conferencia', 'motivo': 'PDF sem texto pesquisável (OCR necessário)'}
    return parse_invoice_text(text)

def stable_id(secret, value, length=12):
    return hmac.new(secret.encode('utf-8'), value.encode('utf-8'), hashlib.sha256).hexdigest()[:length]


class ShareError(RuntimeError):
    pass


class PublicShare:
    def __init__(self, origin, token, password, session=None):
        parts = urlsplit(origin)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query:
            raise ShareError('NUVEM_BASE_URL deve ser um endereço HTTPS válido')
        self.origin = origin.rstrip('/')
        self.token = token
        self.password = password
        self.session = session or requests.Session()
        self.root = None
        self.user = None
        self._host = parts.hostname

    def request(self, method, url, **kwargs):
        if urlsplit(url).hostname != self._host or not url.startswith(self.origin + '/'):
            raise ShareError('Endereço retornado fora do servidor configurado')
        try:
            r = self.session.request(method, url, auth=(self.user, self.password),
                                     headers={**HEADERS, **kwargs.pop('headers', {})},
                                     allow_redirects=False, timeout=(15, 75), **kwargs)
        except requests.RequestException as e:
            # Nao propagar URLs autenticadas ou dados sensiveis em mensagens publicas.
            raise ShareError('Falha de rede ao consultar a Nuvem UTFPR') from e
        if r.status_code in (401, 403):
            raise ShareError('Acesso WebDAV não autorizado (HTTP ' + str(r.status_code) + ')')
        if r.status_code == 404:
            raise ShareError('Endpoint WebDAV não encontrado (HTTP 404)')
        if r.status_code != (207 if method == 'PROPFIND' else 200):
            raise ShareError('Resposta WebDAV inesperada (HTTP ' + str(r.status_code) + ')')
        if len(r.content) > (MAX_XML_BYTES if method == 'PROPFIND' else MAX_PDF_BYTES):
            raise ShareError('Arquivo ou resposta WebDAV excede o limite configurado')
        return r

    def connect(self):
        endpoints = [
            (f'{self.origin}/public.php/dav/files/{quote(self.token, safe="")}/', 'anonymous'),
            (f'{self.origin}/public.php/dav/files/{quote(self.token, safe="")}/', self.token),
            (f'{self.origin}/public.php/webdav/', self.token),
        ]
        errors = []
        for url, user in endpoints:
            self.root, self.user = url, user
            try:
                self.propfind(url)
                return
            except ShareError as ex:
                errors.append(str(ex))
                if 'Falha de rede' in str(ex):
                    break
        self.root, self.user = None, None
        raise ShareError('Sem acesso WebDAV: ' + ' / '.join(dict.fromkeys(errors)))

    def propfind(self, url):
        response = self.request('PROPFIND', url, headers={'Depth':'1', 'Content-Type':'application/xml'},
                                data=b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:allprop/></d:propfind>')
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as e:
            raise ShareError('Resposta WebDAV XML inválida') from e
        items = []
        base = urlsplit(self.root).path
        for entry in root.findall('d:response', NS):
            href = entry.findtext('d:href', default='', namespaces=NS)
            if not href:
                continue
            # Permite href absoluto do mesmo host ou caminho absoluto no mesmo servidor.
            target = urljoin(url, href)
            target_parts = urlsplit(target)
            path = unquote(target_parts.path)
            base_path = unquote(base)
            if target_parts.hostname != self._host or not path.startswith(base_path):
                continue
            # Resposta pode incluir diferentes propstat; seleciona a resposta com HTTP 200.
            prop = None
            for stat in entry.findall('d:propstat', NS):
                if '200' in stat.findtext('d:status', default='', namespaces=NS):
                    prop = stat.find('d:prop', NS)
                    break
            if prop is None:
                continue
            relative = path[len(base_path):].strip('/')
            if not relative:
                continue
            typ = prop.find('d:resourcetype', NS)
            is_dir = typ is not None and typ.find('d:collection', NS) is not None
            etag = prop.findtext('d:getetag', default='', namespaces=NS).strip('"')
            size = prop.findtext('d:getcontentlength', default='', namespaces=NS)
            if size and not size.isdigit():
                size = ''
            # Construir a URL a partir do caminho validado, nunca de um host fornecido por terceiros.
            absolute_url = self.origin + quote(target_parts.path, safe='/%')
            items.append({'relative': relative, 'url': absolute_url,
                          'is_dir': is_dir, 'etag': etag, 'size': int(size) if size else None})
        return items

    def list_pdfs(self):
        folders = [self.root]
        visited = set()
        files = []
        while folders:
            folder = folders.pop(0)
            if folder in visited:
                continue
            visited.add(folder)
            if len(visited) > MAX_FOLDERS:
                raise ShareError('Muitas pastas na Nuvem; limite de segurança atingido')
            for item in self.propfind(folder):
                if item['is_dir']:
                    folders.append(item['url'].rstrip('/') + '/')
                elif item['relative'].lower().endswith('.pdf'):
                    files.append(item)
                    if len(files) > MAX_FILES:
                        raise ShareError('Muitos PDFs na Nuvem; limite de segurança atingido')
        return files

    def download(self, item):
        if item['size'] and item['size'] > MAX_PDF_BYTES:
            return None
        response = self.request('GET', item['url'])
        return response.content


def scan():
    token = os.environ.get('NEXTCLOUD_SHARE_TOKEN', '').strip()
    password = os.environ.get('NEXTCLOUD_SHARE_PASSWORD', '')
    if not token or not password:
        raise ShareError('Configure NEXTCLOUD_SHARE_TOKEN e NEXTCLOUD_SHARE_PASSWORD nos Secrets do GitHub')
    if not re.fullmatch(r'[\w-]{5,128}', token):
        raise ShareError('Identificador do compartilhamento inválido')
    origin = os.environ.get('NUVEM_BASE_URL', DEFAULT_URL)
    client = PublicShare(origin, token, password)
    client.connect()
    files = client.list_pdfs()
    before = read_json(DATA_FILE, {'faturas': []})
    state = read_json(STATE_FILE, {'arquivos': {}})
    previous_files = state.get('arquivos', {})
    old_bills = {f['id']: f for f in before.get('faturas', []) if 'id' in f}
    next_files = {}
    next_bills = {}
    processed = 0
    key = os.environ.get('ENERGIA_ID_CHAVE', '').strip() or password
    for item in files:
        file_id = stable_id(key, item['relative'], 20)
        identity = {'etag': item['etag'], 'tamanho': item['size']}
        next_files[file_id] = identity
        cached = [dict(b) for b in old_bills.values() if b.get('arquivo_id',b['id']) == file_id]
        if (item['etag'] and identity == previous_files.get(file_id) and cached
                and all(b.get('extrator_versao') == PARSER_VERSION for b in cached)):
            for rec in cached:
                rec.pop('origem_removida', None)
                rec['status'] = rec.get('status_extracao', rec['status'])
                rec['motivo'] = rec.get('motivo_extracao', rec.get('motivo'))
                next_bills[rec['id']] = rec
            continue
        pdf = client.download(item)
        records = parse_pdf_records(pdf) if pdf is not None else [{'status':'conferencia','motivo':'PDF excede 15 MB'}]
        # A UC pode ser identificada por um trecho único do documento histórico,
        # sem armazenar ou publicar a UC real.
        historical_uc=None
        if pdf is not None and any(b.get('tipo_documento')=='historico_faturamento' for b in records):
            with fitz.open(stream=pdf,filetype='pdf') as d:
                t=d[0].get_text(sort=False)
                match=re.search(r'Nº\. da UC\.:?\s*(?:.{0,100}\n)?',t)
                nums=re.findall(r'(?m)^\s*\d{8,16}\s*$',t)
                historical_uc=nums[0].strip() if nums else None
        for index,record in enumerate(records):
            source_group = record.pop('_uc', None) or historical_uc or ('pasta:' + item['relative'].rsplit('/', 1)[0])
            rec_id=file_id if len(records)==1 else stable_id(key,file_id+'|'+str(record.get('competencia'))+'|'+str(index),20)
            record['id']=rec_id
            record['arquivo_id']=file_id
            record['extrator_versao']=PARSER_VERSION
            record['status_extracao']=record.get('status','conferencia')
            record['motivo_extracao']=record.get('motivo')
            record['unidade']='UC-'+stable_id(key,source_group,6).upper()
            record['versao']=item['etag'] or hashlib.sha256(pdf or b'').hexdigest()[:16]
            next_bills[rec_id]=record
        processed += 1
    # Itens removidos da origem nao sao apagados automaticamente da base historica;
    # sao mantidos e sinalizados para auditoria, se ja haviam sido importados.
    missing = 0
    for file_id, bill in old_bills.items():
        if bill.get('arquivo_id', file_id) not in next_files:
            item = dict(bill)
            item['origem_removida'] = True
            next_bills[file_id] = item
            missing += 1
    items = sorted(next_bills.values(), key=lambda x: ((x.get('mes_consumo') or x.get('competencia') or ''), x['id']))
    # Uma referência mensal pode aparecer no relatório e na fatura individual.
    # Priorizar documento individual; nunca somar dois documentos da mesma UC/mês.
    grouped = {}
    for r in items:
        if r.get('status') in ('ok','parcial') and not r.get('origem_removida'):
            grouped.setdefault((r['unidade'],r.get('mes_consumo') or r.get('competencia')),[]).append(r)
    for group in grouped.values():
        if len(group)>1:
            singles=[b for b in group if b.get('tipo_documento')=='fatura_individual']
            if len(singles)==1:
                for b in group:
                    if b is not singles[0]:
                        b['status']='duplicado';b['motivo']='Substituído por fatura individual da mesma unidade e período'
            else:
                for b in group:
                    b['status']='conferencia';b['motivo']='Múltiplos documentos para a mesma unidade e período'

    now = now_utc()
    result = {'schema': 2, 'atualizado_em': now, 'faturas': items}
    save_json(DATA_FILE, result)
    save_json(STATE_FILE, {'schema': 1, 'arquivos': next_files})
    save_json(STATUS_FILE, {'estado': 'sucesso', 'ultima_tentativa': now,
                            'ultima_sincronizacao': now, 'arquivos_localizados': len(files),
                            'novos_ou_alterados': processed,
                            'faturas_processadas': sum(b.get('status') in ('ok','parcial') and not b.get('origem_removida') for b in items),
                            'faturas_conferencia': sum(b.get('status') == 'conferencia' or bool(b.get('origem_removida')) for b in items),
                            'faturas_parciais': sum(b.get('status') == 'parcial' for b in items),
                            'faturas_duplicadas': sum(b.get('status') == 'duplicado' for b in items),
                            'origens_removidas': missing, 'mensagem': 'Consulta WebDAV concluída'})
    return len(files), processed


def main():
    args = argparse.ArgumentParser(description='Sincronização somente leitura de faturas Copel por WebDAV')
    args.add_argument('--teste-conexao', action='store_true', help='Somente verificar PROPFIND; não grava JSON')
    cfg = args.parse_args()
    try:
        if cfg.teste_conexao:
            token = os.environ.get('NEXTCLOUD_SHARE_TOKEN', '').strip()
            password = os.environ.get('NEXTCLOUD_SHARE_PASSWORD', '')
            if not token or not password:
                raise ShareError('Configure os Secrets de acesso antes do teste')
            s = PublicShare(os.environ.get('NUVEM_BASE_URL', DEFAULT_URL), token, password)
            s.connect()
            files = s.list_pdfs()
            print(f'WebDAV OK: {len(files)} arquivos PDF acessíveis (somente leitura)')
            return 0
        count, processed = scan()
        print(f'Sincronização: {count} PDF(s) encontrados, {processed} novo(s) ou alterado(s).')
        return 0
    except ShareError as ex:
        msg = str(ex)
        print('Falha na sincronização: ' + msg, file=sys.stderr)
        if not cfg.teste_conexao:
            previous = read_json(STATUS_FILE, {})
            save_json(STATUS_FILE, {'estado':'erro', 'ultima_tentativa':now_utc(),
                                     'ultima_sincronizacao':previous.get('ultima_sincronizacao'),
                                     'arquivos_localizados':previous.get('arquivos_localizados',0),
                                     'faturas_processadas':previous.get('faturas_processadas',0),
                                     'faturas_conferencia':previous.get('faturas_conferencia',0),
                                     'novos_ou_alterados':0, 'mensagem':msg})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
