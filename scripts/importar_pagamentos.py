#!/usr/bin/env python3
"""Espelha o resumo público do PWA anterior sem reclassificar nem duplicar valores.
Esse projeto novo ainda depende da conciliação CGU+SEI do PWA anterior.
"""
import json, sys, tempfile, os
from pathlib import Path
from urllib.request import Request, urlopen
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1]
URL='https://igorguiz.github.io/gestao-contratos-utfpr/data/resumo.json'
OUT=ROOT/'data'/'pagamentos.json'
def run():
    with urlopen(Request(URL,headers={'User-Agent':'DEPRO-LD/1.2'}),timeout=60) as r:
        src=json.load(r)
    if src.get('versao')!=3 or not isinstance(src.get('notas'),list) or src.get('status') not in ('ok','sei_parcial'):
        raise ValueError('Fonte anterior não contém conciliação válida; preservar dados existentes')
    if src.get('ug')!='150148':raise ValueError('UG incompatível')
    notes=[x for x in src['notas'] if x.get('cnpj') in ('82395773000189','82.395.773/0001-89') and str(x.get('mes_pagamento','')).startswith('2026-')]
    # Não aceitamos somas sem controle de categoria ou dados de documentos.
    required=('valor_bruto_centavos','mes_pagamento','categoria','tipo_registro')
    if any(any(k not in n for k in required) for n in notes):raise ValueError('Formato das notas mudou')
    if not notes:raise ValueError('Nenhuma nota ARCOLON para 2026; não atualizar')
    allowed=('Serviços','Materiais','Não classificado')
    if any(n['categoria'] not in allowed for n in notes):raise ValueError('Categoria não reconhecida')
    result={'schema_version':1,'fonte':URL,'fonte_atualizada_em':src.get('atualizado_em'),
      'importado_em':datetime.now(timezone.utc).isoformat(timespec='seconds'),
      'metodologia':'Valores brutos pagos, com retenções; conciliados no PWA anterior CGU+SEI',
      'notas':notes,'pendencias':[x for x in src.get('pendencias',[]) if x.get('cnpj') in ('82395773000189','82.395.773/0001-89') and str(x.get('mes','')).startswith('2026-')]}
    OUT.parent.mkdir(exist_ok=True,parents=True)
    tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8');tmp.replace(OUT)
    print('Notas de pagamento ARCOLON importadas:',len(notes),'bruto (centavos):',sum(x['valor_bruto_centavos'] for x in notes))
if __name__=='__main__':
    try:run()
    except Exception as exc:print('ERRO (dados anteriores preservados):',exc,file=sys.stderr);sys.exit(1)
