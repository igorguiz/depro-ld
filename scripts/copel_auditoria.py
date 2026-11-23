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

def audit_lines(page_texts, record, layout):
    """Cruza linhas discriminadas do DANF3E ou fatura antiga com valores do extrator.

    Retorna evidencias sem texto original; divergencias criticas exigem conferencia.
    """
    results, issues = {}, []
    if layout not in ('danf3e', 'fatura_legada'):
        return results, issues
    first = normalize(page_texts[0])
    last = normalize(page_texts[-1])
    labels = {
        'te_ponta': r'ENERGIA ELETRICA TE PONTA',
        'tusd_ponta': r'ENERGIA ELETRICA (?:USD|TUSD) PONTA',
        'te_fora_ponta': r'ENERGIA ELETRICA TE F\s*PONTA',
        'tusd_fora_ponta': r'ENERGIA ELETRICA (?:USD|TUSD) F\s*PONTA',
    }
    for ident, pattern in labels.items():
        # Na primeira pagina (DANF3E), ha unidades e quantidade, preco e valor.
        rx = r'(?m)^\s*' + pattern + r'\s+KWH\s+(' + NUMBER + r')\s+(' + NUMBER + r')\s+(' + NUMBER + r')(?=\s|$)'
        m = re.search(rx, first)
        source = 'primeira_pagina'
        if not m:
            # Extrato: leituras anterior/atual, medido, faturado, preco, valor.
            rx2 = r'(?m)^\s*'+pattern+r'\s+\d+\s+\d+\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')(?=\s|$)'
            lm = re.search(rx2, last)
            if lm:
                quantities = (lm.group(2), lm.group(3), lm.group(4))
                source = 'extrato_tecnico'
            else:
                continue
        else:
            quantities = (m.group(1), m.group(2), m.group(3))
        quantity, price, amount = map(decimal_pt, quantities)
        if None in (quantity, price, amount):
            continue
        theoretical = quantity * price
        # Preco publicado pode ser arredondado a 6 casas; tolerancia proporcional
        # ao arredondamento + 1 centavo de arredondamento monetario.
        decimals = len(quantities[1].split(',')[-1]) if ',' in quantities[1] else 0
        tolerance = Decimal('0.01') + quantity * (Decimal(10) ** (-decimals)) / 2
        delta = abs(theoretical - amount)
        valid = delta <= tolerance
        results[ident] = {'regra': 'linha_quantidade_preco_valor', 'origem': source,
                          'confianca': 'alta' if valid else 'baixa',
                          'validado': valid, 'diferenca_reais': float(delta.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                          'tolerancia_reais': float(tolerance.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))}
        if not valid: issues.append(f'inconsistencia_aritmetica_{ident}')
        for field, expected in [('preco_faturado_'+ident, price), ('valor_'+ident+'_reais', amount)]:
            extracted = record.get(field)
            if extracted is not None:
                actual = Decimal(str(extracted))
                threshold = Decimal('0.000001') if field.startswith('preco_') else Decimal('0.01')
                if abs(actual - expected) > threshold:
                    issues.append('divergencia_coluna_'+field)
    return results, issues

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
    """Audita um registro e retorna auditoria externa + campos publicos nao sensiveis."""
    text = '\n'.join(page_texts)
    layout = classify(text)
    evidence = {'layout':layout or 'layout_desconhecido', 'campos':{}, 'alertas':[]}
    updates = {'layout_detectado':layout or 'layout_desconhecido'}
    issues = evidence['alertas']
    if layout is None:
        issues.append('layout_desconhecido')
        return evidence,updates,issues
    if layout == 'danf3e':
        keys = nf3e_candidates(page_texts[0])
        if len(keys) == 1:
            # chave da NF3e representa nota fiscal, nao PDF
            updates['chave_nf3e_id'] = hmac.new(secret.encode(),('nf3e|'+keys[0]).encode(),hashlib.sha256).hexdigest()[:24]
            evidence['campos']['chave_nf3e'] = {'regra':'44_digitos_dv_mod11', 'confianca':'alta','validado':True}
        else:
            issues.append('chave_nf3e_nao_identificada_ou_ambigua')
            evidence['campos']['chave_nf3e'] = {'regra':'44_digitos_dv_mod11','confianca':'baixa','validado':False}
    lines, errors = audit_lines(page_texts,record,layout)
    evidence['campos'].update(lines)
    issues.extend(errors)
    if layout != 'historico_cmehfat0':
        total_evidence, total_errors = audit_total(page_texts,record,layout)
        evidence['campos']['valor_centavos'] = total_evidence
        issues.extend(total_errors)
    if layout == 'historico_cmehfat0':
        # Os tres indicadores minimos dos historicos
        for field in ('consumo_kwh_ponta','consumo_kwh_fora_ponta','valor_centavos'):
            value = record.get(field)
            evidence['campos'][field] = {'regra':'bloco_mensal_historico', 'confianca':'media' if value is not None else 'baixa', 'validado':value is not None}
            if value is None: issues.append('historico_sem_'+field)
    else:
        # Fallback sem evidencia independente nao e prova de valor certo
        for field in ('consumo_kwh',):
            evidence['campos'][field] = {'regra':'rotulo_especifico_ou_fallback_v16', 'confianca':'media' if record.get(field) is not None else 'baixa', 'validado':record.get(field) is not None}
            if record.get(field) is None: issues.append('campo_essencial_ausente_'+field)
        # conferência de consistência de dois postos sem exigir igualdade exata a medicao
        p,f,tot = (record.get(k) for k in ('consumo_kwh_ponta','consumo_kwh_fora_ponta','consumo_kwh'))
        if None not in (p,f,tot) and abs(p+f-tot)>1.01:
            issues.append('divergencia_consumo_total')
    return evidence,updates,list(dict.fromkeys(issues))
