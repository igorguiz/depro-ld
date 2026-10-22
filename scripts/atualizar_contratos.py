#!/usr/bin/env python3
"""Coleta pública, somente leitura, dos dados cadastrais de contratos.
Não usa credenciais e não altera dados existentes se a validação falhar.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'contratos.json'
OUTPUT = ROOT / 'data' / 'contratos.json'
BASE = 'https://contratos.comprasnet.gov.br/transparencia/contratos/'


def tidy(s):
    return re.sub(r'\s+', ' ', s or '').strip()


def collect_pairs(html):
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()
    pairs = {}
    # A tabela principal da consulta possui linhas com rótulo e valor.
    for tr in soup.find_all('tr'):
        cells = tr.find_all(['th', 'td'], recursive=False)
        if len(cells) < 2:
            continue
        key = tidy(cells[0].get_text(' ', strip=True))
        val = tidy(cells[1].get_text(' ', strip=True))
        if key and val and len(key) < 100:
            pairs.setdefault(key.casefold(), val)
    return pairs


def pick(pairs, *labels):
    for label in labels:
        value = pairs.get(label.casefold())
        if value:
            return value
    return ''


def extract(html, cfg):
    pairs = collect_pairs(html)
    number = pick(pairs, 'Número Contrato', 'Número do Contrato')
    supplier = pick(pairs, 'Fornecedor')
    process = pick(pairs, 'Processo')
    start = pick(pairs, 'Vig. Início', 'Vig. Inicio')
    end = pick(pairs, 'Vig. Fim')
    situation = pick(pairs, 'Situação', 'Situacao')
    global_value = pick(pairs, 'Valor Global')
    # Alguns layouts incluem símbolo de informação junto ao rótulo.
    if not global_value:
        global_value = next((v for k, v in pairs.items() if k.startswith('valor global')), '')
    if not all([number, supplier, process, start, end, situation, global_value]):
        missing = [k for k, v in {'numero':number, 'fornecedor':supplier, 'processo':process, 'inicio':start, 'fim':end, 'situacao':situation, 'valor_global':global_value}.items() if not v]
        raise ValueError(f'Campos não encontrados na consulta {cfg["id_comprasnet"]}: {missing}')
    normalized_number = re.sub(r'^0+(?=\d)', '', number.strip())
    if normalized_number != cfg['numero']:
        raise ValueError(f'Número inesperado: {number!r} != {cfg["numero"]!r}')
    if cfg['cnpj'] not in supplier:
        raise ValueError(f'CNPJ inesperado no fornecedor: {supplier!r}')
    if not re.fullmatch(r'\d{2}/\d{2}/\d{4}', start) or not re.fullmatch(r'\d{2}/\d{2}/\d{4}', end):
        raise ValueError('Formato inválido de vigência')
    if not re.search(r'\d{1,3}(?:\.\d{3})*,\d{2}', global_value):
        raise ValueError(f'Valor global inválido: {global_value!r}')
    if not re.fullmatch(r'\d{5}\.\d{6}/\d{4}-\d{2}', process):
        raise ValueError(f'Número de processo inesperado: {process!r}')
    return {
        'id':cfg['id'], 'id_comprasnet':cfg['id_comprasnet'], 'numero':normalized_number,
        'fornecedor':supplier, 'cnpj':cfg['cnpj'], 'processo_licitacao':process,
        'vigencia_inicio':start, 'vigencia_fim':end, 'situacao':situation,
        'valor_global':global_value, 'url_fonte':BASE+str(cfg['id_comprasnet']),
        'consultado_em':datetime.now(timezone.utc).isoformat(timespec='seconds')
    }


def run():
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    session = requests.Session()
    session.headers.update({'User-Agent':'Mozilla/5.0 (compatible; UTFPR-DEPRO-LD/1.0; consulta-publica)', 'Accept-Language':'pt-BR,pt;q=0.9', 'Accept':'text/html'})
    rows = []
    for cfg in config['contratos']:
        url = BASE+str(cfg['id_comprasnet'])
        response = session.get(url, timeout=35)
        response.raise_for_status()
        if 'html' not in response.headers.get('Content-Type','').lower():
            raise ValueError(f'Resposta não HTML para {cfg["id"]}')
        data = extract(response.text, cfg)
        rows.append(data)
        print(f'OK: {data["numero"]} / {data["fornecedor"]} / {data["valor_global"]}')
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT.with_suffix('.tmp')
    tmp.write_text(json.dumps({'schema_version':1,'atualizado_em':datetime.now(timezone.utc).isoformat(timespec='seconds'),'contratos':rows},indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    tmp.replace(OUTPUT)
    print('Arquivo gerado:', OUTPUT)

if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print('ERRO: dados preservados. A atualização não foi publicada.', str(exc),file=sys.stderr)
        sys.exit(1)
