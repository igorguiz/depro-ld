"""Auditoria independente de campos extraidos das faturas Copel.

Nao publica evidencias textuais nem identificadores fiscais em claro. Os identificadores
HMAC sao gerados pelo sincronizador. Os PDFs continuam na origem Nextcloud.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

NUMBER = r'-?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?'
FORMATS = {
    'historico_cmehfat0': ('CMEHFAT0', 'HISTORICO DE FATURAMENTO'),
    'danf3e': ('DANF3E', 'NOTA FISCAL ELETRONICA DE ENERGIA ELETRICA'),
    'fatura_legada': ('NOTA FISCAL/CONTA DE ENERGIA ELETRICA', 'VALORES FATURADOS'),
}

def normalize(text):
    """Preserva os numeros/pontuacao; remove acentos e unifica brancos e caixa."""
    text = unicodedata.normalize('NFKD', text.replace('\u00a0', ' '))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'[ \t\f\v]+', ' ', text).upper()

def decimal_pt(s):
    if s is None:
        return None
    raw = str(s).strip().replace(' ', '')
    if ',' in raw:
        raw = raw.replace('.', '').replace(',', '.')
    elif re.fullmatch(r'\d{1,3}(?:\.\d{3})+', raw):
        raw = raw.replace('.', '')
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None

def classify(text):
    normalized = normalize(text)
    for name, labels in FORMATS.items():
        if all(label in normalized for label in labels):
            return name
    return None

def nf3e_valid(key):
    if not (re.fullmatch(r'\d{44}', key) and key[20:22] == '66'):
        return False
    weight = 2
    total = 0
    for digit in reversed(key[:43]):
        total += int(digit) * weight
        weight = weight + 1 if weight < 9 else 2
    check = (11 - total % 11) % 11
    if check == 10: check = 0
    return check == int(key[-1])

def nf3e_candidates(text):
    """Restrito ao entorno da etiqueta Chave de Acesso, inclusive texto embaralhado.

    Evita extrair 44 digitos arbitrarios de tabelas de medicao.
    """
    candidates = []
    for line in text.splitlines():
        up = normalize(line)
        if 'CHAVE' not in up or 'ACESSO' not in up:
            continue
        compact = re.sub(r'CHAVE|DE|ACESSO', ' ', up)
        digits = re.findall(r'(?<!\d)\d{4}(?!\d)', compact)
        for start in range(max(0, len(digits) - 10)):
            k = ''.join(digits[start:start+11])
            if len(k) == 44 and nf3e_valid(k): candidates.append(k)
        # Alguns PDF misturam as palavras entre os blocos de numeros
        if len(digits) == 11:
            k = ''.join(digits)
            if nf3e_valid(k): candidates.append(k)
    return list(dict.fromkeys(candidates))

# Expressões reconhecidas pelo layout; cada rubrica tem natureza própria.
# Fatura legada não separa TE/TUSD e NUNCA deve ser rebatizada como TE.
ITEM_LABELS = {
    'te_ponta': r'ENERGIA ELETRICA TE PONTA',
    'tusd_ponta': r'ENERGIA ELETRICA (?:USD|TUSD) PONTA',
    'te_fora_ponta': r'ENERGIA ELETRICA TE F\s*PONTA',
    'tusd_fora_ponta': r'ENERGIA ELETRICA (?:USD|TUSD) F\s*PONTA',
    'legada_ponta': r'ENERGIA ELET CONSUMO PTA',
    'legada_fora_ponta': r'ENERGIA ELET CONSUMO F PTA',
}


def extract_billing_rows(page_texts, layout):
    """Retorna rubricas explícitas com quantidade, preço e valor, em qualquer página.

    Prefere linha fiscal ``kWh quantidade preço valor``; o extrato técnico
    serve como segunda evidência ``leitura_ant leitura_atual medido faturado preço valor``.
    Não deduz rubricas ausentes, não deduz TE/TUSD a partir de fatura legada.
    """
    found = {}
    selected = (('legada_ponta', 'legada_fora_ponta') if layout == 'fatura_legada'
                else ('te_ponta', 'tusd_ponta', 'te_fora_ponta', 'tusd_fora_ponta'))
    for ident in selected:
        label = ITEM_LABELS[ident]
        rx_fiscal = re.compile(r'(?m)^\s*'+label+r'\s+KWH\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')(?=\s|$)')
        rx_tech = re.compile(r'(?m)^\s*'+label+r'\s+\d+\s+\d+\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')(?=\s|$)')
        options = []
        for i, page in enumerate(page_texts):
            text = normalize(page)
            for match in rx_fiscal.finditer(text):
                options.append((0, i, 'tabela_fiscal', (match.group(1),match.group(2),match.group(3))))
            for match in rx_tech.finditer(text):
                options.append((1, i, 'extrato_tecnico', (match.group(2),match.group(3),match.group(4))))
        if not options:
            continue
        options.sort(key=lambda x:(x[0],x[1]))
        _, page_index, source, raw = options[0]
        qty, price, amount = (decimal_pt(x) for x in raw)
        if None in (qty, price, amount):
            continue
        found[ident] = {
            'quantidade': float(qty), 'preco': float(price), 'valor': float(amount),
            'raw_preco': raw[1], 'pagina': page_index+1, 'origem': source,
            'evidencias': len(options),
        }
    return found


def extract_meter_total(page_texts):
    """Exclusivamente ENERGIA ELETRICA CONSUMO no extrato de medição.

    Em várias segundas vias a linha está colada a outra linha; não exige ^.
    A linha fiscal ENERGIA ELETRICA CONSUMO kWh 0,00 não é o total medido.
    """
    pattern = re.compile(r'\bENERGIA\s+ELETRICA\s+CONSUMO\s+\d+\s+\d+\s+('+NUMBER+r')(?=\s|$)')
    results = []
    for i, page in enumerate(page_texts):
        for match in pattern.finditer(normalize(page)):
            value = decimal_pt(match.group(1))
            if value is not None and value >= 0:
                results.append((i+1, float(value)))
    if not results:
        return None, []
    distinct = sorted({v for _,v in results})
    return (distinct[0] if len(distinct)==1 else None), results


def extract_injection_measurements(page_texts):
    """Lê medições explícitas (nunca soma ponta e fora de ponta)."""
    result = {'ponta': None, 'fora_ponta': None, 'total': None}
    labels = {'ponta':r'ENERGIA GERADA/INJETADA PONTA',
              'fora_ponta':r'ENERGIA GERADA/INJETADA FORA P(?:ONTA)?',
              'total':r'ENERGIA (?:GERADA/)?INJETADA TOTAL'}
    for key, label in labels.items():
        pattern = re.compile(r'\b'+label+r'\s+\d+\s+\d+\s+('+NUMBER+r')(?=\s|$)')
        candidates = []
        for page in page_texts:
            for m in pattern.finditer(normalize(page)):
                val=decimal_pt(m.group(1))
                if val is not None and val >= 0:
                    candidates.append(float(val))
        if len(set(candidates))==1:
            result[key]=candidates[0]
    return result


def extract_regulated_tariffs(page_texts):
    """TUSD e TE apresentados em 'Informações Suplementares' nas DANF3E."""
    result = {}
    for page in page_texts:
        text = normalize(page)
        marker = text.find('INFORMACOES SUPLEMENTARES')
        if marker < 0:
            continue
        segment=text[marker:marker+1200]
        for lab, key in ((r'CONSUMO F PONTA','fora_ponta'),(r'CONSUMO PTA','ponta')):
            m=re.search(r'(?m)^\s*'+lab+r'\s+('+NUMBER+r')\s+('+NUMBER+r')(?=\s|$)',segment)
            if m:
                tusd,te=decimal_pt(m.group(1)),decimal_pt(m.group(2))
                if None not in (tusd,te):
                    result[key]={'tusd':float(tusd),'te':float(te)}
    return result


def audit_lines(page_texts, record, layout):
    """Confere existência, aritmética e exportação de todas as rubricas reconhecidas.

    A falta de rubrica que CONSTA no PDF é erro, inclusive quando o extrator
    antigo deixou o campo null. A rubrica que não consta NÃO é inventada.
    """
    results, issues = {}, []
    if layout not in ('danf3e', 'fatura_legada'):
        return results, issues
    rows=extract_billing_rows(page_texts,layout)
    for ident,row in rows.items():
        quantity,price,amount = (Decimal(str(row[k])) for k in ('quantidade','preco','valor'))
        decimals=len(row['raw_preco'].split(',')[-1]) if ',' in row['raw_preco'] else 0
        tolerance=Decimal('0.01')+quantity*(Decimal(10)**(-decimals))/2
        delta=abs(quantity*price-amount)
        valid=delta<=tolerance
        results[ident]={'regra':'linha_quantidade_preco_valor','origem':row['origem'],
            'pagina':row['pagina'],'confianca':'alta' if valid else 'baixa',
            'validado':valid,
            'diferenca_reais':float(delta.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)),
            'tolerancia_reais':float(tolerance.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))}
        if not valid:issues.append('inconsistencia_aritmetica_'+ident)
        if ident.startswith('legada_'):
            period=ident.replace('legada_','')
            expected=[('preco_energia_legada_'+period,price),('valor_energia_legada_'+period+'_reais',amount)]
        else:
            expected=[('preco_faturado_'+ident,price),('valor_'+ident+'_reais',amount)]
        for field,source_value in expected:
            extracted=record.get(field)
            if extracted is None:
                issues.append('campo_presente_na_fatura_mas_ausente_no_json_'+field)
            else:
                threshold=Decimal('0.000001') if field.startswith('preco_') else Decimal('0.01')
                if abs(Decimal(str(extracted))-source_value)>threshold:
                    issues.append('divergencia_coluna_'+field)
    # Se um rótulo está presente mas falhou tanto a leitura fiscal como técnica,
    # impedimos uma aprovação silenciosa (principalmente nas DANF3E multipágina).
    chosen=('legada_ponta','legada_fora_ponta') if layout=='fatura_legada' else ('te_ponta','tusd_ponta','te_fora_ponta','tusd_fora_ponta')
    full='\n'.join(normalize(p) for p in page_texts)
    for ident in chosen:
        if ident not in rows and re.search(ITEM_LABELS[ident],full):
            issues.append('rubrica_nao_interpretada_'+ident)
    return results, list(dict.fromkeys(issues))


def audit_total(page_texts, record, layout):
    """Confere o valor final contra a secao de pagamento ou TOTAL, sem procurar R$ solto."""
    first = normalize(page_texts[0])
    if layout == 'danf3e':
        regex = r'(?m)^\s*TOTAL\s+('+NUMBER+r')\s+'
        rule = 'total_linha_faturamento'
    elif layout == 'fatura_legada':
        regex = r'VALOR A PAGAR\s*\n\s*\d{2}/\d{2}/20\d{2}\s+('+NUMBER+r')'
        rule = 'valor_a_pagar_cabecalho'
    else:
        return None, []
    m = re.search(regex, first)
    if not m:
        return {'regra':'fallback_v16_sem_confirmacao','confianca':'baixa','validado':False}, ['total_sem_rotulo_confirmado']
    amount = decimal_pt(m.group(1))
    got = record.get('valor_centavos')
    if amount is None or got is None:
        return {'regra':rule,'confianca':'baixa','validado':False}, ['total_nao_identificado']
    ok = int((amount*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))==got
    return {'regra':rule,'confianca':'alta' if ok else 'baixa','validado':ok}, ([] if ok else ['total_diverge_do_cabecalho'])

def review_document(page_texts, record, secret):
    """Auditoria de documento; nunca considera ausência legítima de histórico erro."""
    text='\n'.join(page_texts)
    layout=classify(text)
    evidence={'layout':layout or 'layout_desconhecido','campos':{},'alertas':[]}
    updates={'layout_detectado':layout or 'layout_desconhecido'}
    issues=evidence['alertas']
    if layout is None:
        issues.append('layout_desconhecido')
        return evidence,updates,issues
    if layout=='danf3e':
        keys=nf3e_candidates(page_texts[0])
        if len(keys)==1:
            updates['chave_nf3e_id']=hmac.new(secret.encode(),('nf3e|'+keys[0]).encode(),hashlib.sha256).hexdigest()[:24]
            evidence['campos']['chave_nf3e']={'regra':'44_digitos_dv_mod11','confianca':'alta','validado':True}
        else:
            issues.append('chave_nf3e_nao_identificada_ou_ambigua')
            evidence['campos']['chave_nf3e']={'regra':'44_digitos_dv_mod11','confianca':'baixa','validado':False}
    lines,errors=audit_lines(page_texts,record,layout)
    evidence['campos'].update(lines)
    issues.extend(errors)
    if layout!='historico_cmehfat0':
        total_evidence,total_errors=audit_total(page_texts,record,layout)
        evidence['campos']['valor_centavos']=total_evidence
        issues.extend(total_errors)
        meter, samples=extract_meter_total(page_texts)
        current=record.get('consumo_kwh')
        valid=(meter is not None and current is not None and abs(meter-float(current))<0.000001)
        evidence['campos']['consumo_kwh']={'regra':'medicao_energia_eletrica_consumo',
            'confianca':'alta' if valid else 'baixa','validado':valid,
            'quantidade_evidencias':len(samples)}
        if not valid:issues.append('consumo_total_sem_medicao_conferida')
        injection=extract_injection_measurements(page_texts)
        for period in ('ponta','fora_ponta'):
            expected=injection[period]
            got=record.get('energia_injetada_kwh_'+period)
            if expected is not None and (got is None or abs(float(got)-expected)>0.000001):
                issues.append('injetada_divergente_'+period)
        # Null explícito é correto quando o documento não apresenta total injetado.
        if injection['total'] is None and record.get('energia_injetada_kwh') is not None:
            issues.append('energia_injetada_total_derivada_sem_rotulo')
        if injection['total'] is not None and record.get('energia_injetada_kwh')!=injection['total']:
            issues.append('energia_injetada_total_divergente')
        # Só se exige TE/TUSD quando o layout/tabela de fato os apresenta.
        if layout=='danf3e':
            tariffs=extract_regulated_tariffs(page_texts)
            for period,values in tariffs.items():
                for nature,expected in values.items():
                    field='tarifa_'+nature+'_'+period
                    got=record.get(field)
                    if got is None or abs(float(got)-expected)>0.000001:
                        issues.append('tarifa_apresentada_mas_ausente_ou_divergente_'+field)
    else:
        for field in ('consumo_kwh_ponta','consumo_kwh_fora_ponta','valor_centavos'):
            val=record.get(field)
            evidence['campos'][field]={'regra':'bloco_mensal_historico',
                'confianca':'media' if val is not None else 'baixa','validado':val is not None}
            if val is None:issues.append('historico_sem_'+field)
        # Histórico: não existe consumo total na linha Qtd; não somamos postos.
        if record.get('consumo_kwh') is not None:
            issues.append('historico_total_consumo_nao_documentado')
    return evidence,updates,list(dict.fromkeys(issues))
