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

import fitz
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


def parse_pdf_invoice(pdf_bytes):
    """Extracao conservadora; dados ambiguos nunca viram valores estimados."""
    try:
        with fitz.open(stream=pdf_bytes, filetype='pdf') as doc:
            if doc.is_encrypted:
                return {'status': 'conferencia', 'motivo': 'PDF protegido por senha'}
            text = '\n'.join(page.get_text(sort=True) for page in (doc[i] for i in range(min(len(doc), 8))))
    except Exception:
        return {'status': 'conferencia', 'motivo': 'PDF inválido ou ilegível'}
    if len(text.strip()) < 55:
        return {'status': 'conferencia', 'motivo': 'PDF sem texto pesquisável (OCR necessário)'}

    # Procura somente rotulos especificos para nao confundir consumo com leitura de medidor
    # nem valor da conta com imposto, base de calculo ou outros subtotais.
    month = find_after_label(text, [
        r'(?<!\w)M[eê]s\s+de\s+refer[eê]ncia', r'(?<!\w)Refer[eê]ncia(?:\s+de\s+faturamento)?',
        r'(?<!\w)Compet[eê]ncia', r'(?<!\w)M[eê]s\s*/\s*Ano',
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
    # Nao procurar valor generico "TOTAL", pois pode ser valor de impostos/encargos.
    amount = find_after_label(text, [
        r'(?<!\w)TOTAL\s+A\s+PAGAR', r'(?<!\w)VALOR\s+TOTAL\s+DA\s+FATURA',
        r'(?<!\w)VALOR\s+DA\s+FATURA', r'(?<!\w)TOTAL\s+DA\s+FATURA',
        r'(?<!\w)VALOR\s+A\s+PAGAR',
    ], r'-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}')
    consumption = find_after_label(text, [
        r'(?<!\w)CONSUMO\s+TOTAL\s*(?:\(\s*kWh\s*\)|em\s+kWh)',
        r'(?<!\w)CONSUMO\s*(?:\(\s*kWh\s*\)|EM\s+kWh|kWh)',
        r'(?<!\w)ENERGIA\s+CONSUMIDA\s*(?:\(\s*kWh\s*\)|kWh)',
    ], r'(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?')
    # Somente campos com expressao de demanda medida (nao contratada).
    demand = find_after_label(text, [
        r'(?<!\w)DEMANDA\s+MEDIDA\s*(?:\(\s*kW\s*\)|kW)?',
        r'(?<!\w)DEMANDA\s+REGISTRADA\s*(?:\(\s*kW\s*\)|kW)?',
    ], r'(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?')
    # Identificador interno: NUNCA e publicado (nao usar como chave publica).
    uc = find_after_label(text, [
        r'(?<!\w)UNIDADE\s+CONSUMIDORA\s*(?:N[º°o.]*)?',
        r'(?<!\w)N[º°o.]*\s+DA\s+UC',
        r'(?<!\w)INSTALA[CÇ][AÃ]O\s*N[º°o.]*',
    ], r'\d[\d.\-]{4,20}')

    value = parse_money(amount)
    kwh = parse_decimal(consumption)
    kw = parse_decimal(demand)
    problems = []
    if comp is None:
        problems.append('competência não identificada')
    if value is None or value < 0:
        problems.append('valor total não identificado')
    if kwh is None or kwh < 0:
        problems.append('consumo em kWh não identificado')
    if consumption is not None and kwh is not None and kwh > 100000000:
        problems.append('consumo fora do intervalo esperado')
    return {
        'status': 'conferencia' if problems else 'ok',
        'motivo': '; '.join(problems) if problems else None,
        'competencia': comp,
        'valor_centavos': value if value is not None and value >= 0 else None,
        'consumo_kwh': kwh if kwh is not None and kwh >= 0 else None,
        'demanda_medida_kw': kw if kw is not None and kw >= 0 else None,
        '_uc': re.sub(r'\D', '', uc) if uc else None,
    }


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
    # A chave HMAC e usada apenas na geracao de identificadores pseudonimos;
    # configurar chave exclusiva evita altera-los quando a senha WebDAV for trocada.
    for item in files:
        file_id = stable_id(key, item['relative'], 20)
        identity = {'etag': item['etag'], 'tamanho': item['size']}
        next_files[file_id] = identity
        if item['etag'] and identity == previous_files.get(file_id) and file_id in old_bills:
            cached = dict(old_bills[file_id])
            cached.pop('origem_removida', None)
            cached['status'] = cached.get('status_extracao', cached['status'])
            cached['motivo'] = cached.get('motivo_extracao', cached.get('motivo'))
            next_bills[file_id] = cached
            continue
        pdf = client.download(item)
        if pdf is None:
            record = {'status': 'conferencia', 'motivo': 'PDF excede 15 MB',
                      'competencia': None, 'valor_centavos': None, 'consumo_kwh': None,
                      'demanda_medida_kw': None, '_uc': None}
        else:
            record = parse_pdf_invoice(pdf)
        source_group = record.pop('_uc', None) or ('pasta:' + item['relative'].rsplit('/', 1)[0])
        record['id'] = file_id
        record['status_extracao'] = record['status']
        record['motivo_extracao'] = record['motivo']
        record['unidade'] = 'UC-' + stable_id(key, source_group, 6).upper()
        record['versao'] = item['etag'] or hashlib.sha256(pdf or b'').hexdigest()[:16]
        next_bills[file_id] = record
        processed += 1
    # Itens removidos da origem nao sao apagados automaticamente da base historica;
    # sao mantidos e sinalizados para auditoria, se ja haviam sido importados.
    missing = 0
    for file_id, bill in old_bills.items():
        if file_id not in next_files:
            item = dict(bill)
            item['origem_removida'] = True
            next_bills[file_id] = item
            missing += 1
    items = sorted(next_bills.values(), key=lambda x: ((x.get('competencia') or ''), x['id']))
    # PDFs com o mesmo valor/mes e UC nao devem ser somados de forma silenciosa.
    # Marcar duplicidade para conferencia; nenhuma contagem financeira dupla.
    grouped = {}
    for r in items:
        if r.get('status') == 'ok' and not r.get('origem_removida'):
            grouped.setdefault((r['unidade'], r['competencia']), []).append(r)
    for group in grouped.values():
        if len(group) > 1:
            for r in group:
                r['status'] = 'conferencia'
                r['motivo'] = 'Mais de uma fatura para a mesma unidade e competência'

    now = now_utc()
    result = {'schema': 1, 'atualizado_em': now, 'faturas': items}
    save_json(DATA_FILE, result)
    save_json(STATE_FILE, {'schema': 1, 'arquivos': next_files})
    save_json(STATUS_FILE, {'estado': 'sucesso', 'ultima_tentativa': now,
                            'ultima_sincronizacao': now, 'arquivos_localizados': len(files),
                            'novos_ou_alterados': processed,
                            'faturas_processadas': sum(b.get('status') == 'ok' and not b.get('origem_removida') for b in items),
                            'faturas_conferencia': sum(b.get('status') != 'ok' or bool(b.get('origem_removida')) for b in items),
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
