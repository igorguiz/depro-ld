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


def extract_demand_measurements(page_texts, layout="danf3e"):
    """Lê a linha técnica DEMANDA USD por rótulo, com 0 ou 2 leituras opcionais.

    Exclui DEMANDA USD ISENTA ICMS e outras rubricas que não representam
    a grandeza medida. Não depende de início de linha (marca Segunda Via).
    A tripla (medida, contratada, faturada) deve estar no mesmo bloco.
    """
    number = r'(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?'
    # Tabela técnica: opcionalmente leituras inteiras, em seguida três
    # grandezas kW com vírgula decimal. Tarifa após a tripla é evidência
    # adicional, mas pode aparecer em páginas/linhas distintas.
    rx = re.compile(
        (r'\bDEMANDA\s+USD(?!\s+ISENTA)\s+' if layout!='fatura_legada' else r'\bDEMANDA(?:[ \t]+USD(?![ \t]+ISENTA))?[ \t]+') +
        r'(?:\d+\s+\d+\s+)?'
        r'('+number+r')\s+('+number+r')\s+('+number+r')(?=\s|$)')
    matches=[]
    for page_no, page in enumerate(page_texts,1):
        for line in normalize(page).splitlines():
            for m in rx.finditer(line):
                values = tuple(decimal_pt(m.group(i)) for i in (1,2,3))
                if any(x is None or x < 0 for x in values):
                    continue
                # Evitar ler os três primeiros números de cinco leituras,
                # exigindo vírgula decimal ao menos na medida e no faturado.
                if ',' not in m.group(1) or ',' not in m.group(3):
                    continue
                matches.append({'medida':float(values[0]),
                                'contratada':float(values[1]),
                                'faturada':float(values[2]),'pagina':page_no})
    values_set={ (m['medida'],m['contratada'],m['faturada']) for m in matches }
    if len(values_set)==1:
        return matches[0], matches, False
    return None, matches, len(values_set)>1


def extract_injection_measurements(page_texts, layout=None):
    """Lê energia fisicamente injetada e audita origem dos valores.

    Regras v1.8.2:
    - Total explícito da fatura tem prioridade.
    - Ponta ausente só equivale a zero quando existe medição válida da
      injeção fora de ponta E o layout individual foi identificado.
    - Zero inferido não é confundido com zero medido: ``origem_ponta``
      registra o critério; o total recebe procedência específica.
    - Se existir um total explícito diferente da medição fora ponta, não
      inferir zero na ponta, pois isso contradiz a evidência disponível.
    - Sem qualquer posto medido, ou layout histórico/desconhecido, não
      se preenchem zeros artificiais.
    """
    result = {'ponta': None, 'fora_ponta': None, 'total': None,
              'origem_total': None, 'origem_ponta': None,
              'ambiguidade': False}
    labels = {'ponta':r'ENERGIA GERADA/INJETADA PONTA',
              'fora_ponta':r'ENERGIA GERADA/INJETADA FORA P(?:ONTA)?',
              'total':r'ENERGIA (?:GERADA/)?INJETADA TOTAL'}
    for key, label in labels.items():
        pattern = re.compile(r'\b'+label+r'[ \t]+\d+[ \t]+\d+[ \t]+('+NUMBER+r')(?=\s|$)')
        candidates = []
        for page in page_texts:
            for m in pattern.finditer(normalize(page)):
                val = decimal_pt(m.group(1))
                if val is not None and val >= 0:
                    candidates.append(float(val))
        distinct = set(candidates)
        if len(distinct) == 1:
            result[key] = candidates[0]
        elif len(distinct) > 1:
            result['ambiguidade'] = True
    if result['ponta'] is not None:
        result['origem_ponta'] = 'medicao_explicita'
    elif (not result['ambiguidade']
          and layout in ('danf3e', 'fatura_legada')
          and result['fora_ponta'] is not None
          and (result['total'] is None or abs(result['total']-result['fora_ponta']) < 1e-6)):
        result['ponta'] = 0.0
        result['origem_ponta'] = 'zero_inferido_layout'
    if result['total'] is not None:
        result['origem_total'] = 'total_explicito'
    elif result['ponta'] is not None and result['fora_ponta'] is not None:
        result['total'] = round(result['ponta'] + result['fora_ponta'], 6)
        result['origem_total'] = ('soma_postos_com_zero_inferido'
                                  if result['origem_ponta'] == 'zero_inferido_layout'
                                  else 'soma_postos_medicao')
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
        injection=extract_injection_measurements(page_texts,layout)
        for period in ('ponta','fora_ponta'):
            expected=injection[period]
            got=record.get('energia_injetada_kwh_'+period)
            if expected is not None and (got is None or abs(float(got)-expected)>0.000001):
                issues.append('injetada_divergente_'+period)
        if injection['origem_ponta'] != record.get('origem_injecao_ponta'):
            issues.append('origem_injecao_ponta_divergente')
        evidence['campos']['energia_injetada_kwh_ponta'] = {
            'regra': injection['origem_ponta'] or 'nao_informada',
            'confianca': 'media' if injection['origem_ponta'] == 'zero_inferido_layout' else (
                'alta' if injection['origem_ponta'] == 'medicao_explicita' else 'baixa'),
            'validado': injection['origem_ponta'] == record.get('origem_injecao_ponta'),
        }
        if injection['ambiguidade']:
            issues.append('energia_injetada_medicoes_divergentes')
        total=record.get('energia_injetada_kwh')
        if injection['total'] is None:
            if total is not None:
                issues.append('energia_injetada_total_sem_evidencia')
        elif total is None or abs(float(total)-injection['total'])>0.000001:
            issues.append('energia_injetada_total_divergente')
        if injection['origem_total']=='total_explicito' and injection['ponta'] is not None and injection['fora_ponta'] is not None:
            if abs(injection['total'] - injection['ponta'] - injection['fora_ponta'])>0.000001:
                issues.append('energia_injetada_total_explicito_incoerente_com_postos')
        if injection['origem_total'] != record.get('origem_total_injetado'):
            issues.append('origem_total_injetado_divergente')
        evidence['campos']['energia_injetada_kwh']={
            'regra': injection['origem_total'] or 'postos_insuficientes',
            'confianca': ('media' if injection['origem_total'] == 'soma_postos_com_zero_inferido' else
                           'alta' if injection['total'] is not None and not injection['ambiguidade'] else 'media'),
            'validado':not injection['ambiguidade'] and (injection['total'] is None or total is not None)}
        # Demanda medida, contratada e faturada devem vir de colunas da linha
        # DEMANDA USD. Uma rubrica existente que não foi interpretada é erro.
        demand, demand_evidences, demand_ambiguous=extract_demand_measurements(page_texts,layout)
        if demand_ambiguous:
            issues.append('demanda_linhas_divergentes')
        elif demand is None:
            if any(re.search((r'\bDEMANDA\s+USD(?!\s+ISENTA)' if layout!='fatura_legada' else r'\bDEMANDA[ \t]+\d+'),normalize(p)) for p in page_texts):
                issues.append('demanda_usd_nao_interpretada')
        else:
            for key, source in [('demanda_medida_kw','medida'),('demanda_contratada_kw','contratada'),('demanda_faturada_kw','faturada')]:
                value=record.get(key)
                if value is None or abs(float(value)-demand[source])>0.000001:
                    issues.append('demanda_divergente_'+key)
            evidence['campos']['demanda']={'regra':'demanda_usd_colunas_medida_contratada_faturada',
                'pagina':demand['pagina'],'confianca':'alta','validado':True}
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
