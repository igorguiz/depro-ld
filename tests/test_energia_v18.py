"""Regressões v1.8: nenhuma grandeza inferida, layout-aware, auditoria íntegra.

Sem PDFs reais, só executa os testes sintéticos. Para auditoria integrada,
configure COPEL_TEST_ZIP para o ZIP das contas (não o publique no GitHub).
"""
from __future__ import annotations
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pymupdf
from copel_auditoria import (audit_lines, extract_billing_rows,
    extract_meter_total, extract_injection_measurements, review_document)
import sincronizar_energia as sync


class TestRegrasDocumentais(unittest.TestCase):
    def test_medicao_nao_soma_postos(self):
        page='''DANF3E\nNOTA FISCAL ELETRONICA DE ENERGIA ELETRICA
ENERGIA ELETRICA TE PONTA kWh 8.832 0,573611 5.066,13
ENERGIA ELETRICA TE F PONTA kWh 33.766 0,363432 12.271,66
Segunda Via ENERGIA ELETRICA CONSUMO 0 94718 42600,00
'''
        total, locations=extract_meter_total([page])
        self.assertEqual(total,42600)
        data=extract_billing_rows([page],'danf3e')
        self.assertEqual(data['te_ponta']['quantidade'],8832)
        self.assertEqual(data['te_fora_ponta']['quantidade'],33766)
        self.assertNotEqual(total,sum(data[k]['quantidade'] for k in ('te_ponta','te_fora_ponta')))
    def test_historico_sem_total_ficticio(self):
        src=Path('/mnt/data/00 2018 a 03 2019-1.pdf')
        if not src.exists():self.skipTest('PDF histórico não está no ambiente')
        records=sync.parse_pdf_records(src.read_bytes())
        self.assertEqual(len(records),12)
        self.assertTrue(all(r['consumo_kwh'] is None for r in records))
        self.assertTrue(all(r['status']=='parcial' for r in records))
    def test_injecao_nao_soma_ponta_fora(self):
        page='''ENERGIA GERADA/INJETADA PONTA 0 15 1,00
ENERGIA GERADA/INJETADA FORA P 151921 445190 36951,00'''
        result=extract_injection_measurements([page])
        self.assertEqual(result['ponta'],1)
        self.assertEqual(result['fora_ponta'],36951)
        self.assertIsNone(result['total'])
    def test_tarifa_presente_nula_gera_alerta(self):
        source='ENERGIA ELETRICA TE PONTA kWh 100,00 0,500000 50,00'
        _,warnings=audit_lines([source], {'preco_faturado_te_ponta':None,'valor_te_ponta_reais':None},'danf3e')
        self.assertIn('campo_presente_na_fatura_mas_ausente_no_json_preco_faturado_te_ponta',warnings)
        self.assertIn('campo_presente_na_fatura_mas_ausente_no_json_valor_te_ponta_reais',warnings)
    def test_tarifa_que_nao_existe_nao_gera_alerta(self):
        _,issues=audit_lines(['NOTA FISCAL/CONTA DE ENERGIA ELETRICA\nVALORES FATURADOS'],{},'fatura_legada')
        self.assertEqual(issues,[])
    def test_legado_nao_rebatizar_energia_como_te(self):
        page='ENERGIA ELET CONSUMO PTA kWh 2.778,00 2,127199 5.909,36'
        data=extract_billing_rows([page],'fatura_legada')
        self.assertEqual(data['legada_ponta']['valor'],5909.36)
        self.assertNotIn('te_ponta',data)
    def test_multiplas_paginas(self):
        pages=['DANF3E\nNOTA FISCAL ELETRONICA DE ENERGIA ELETRICA',
               'ENERGIA ELETRICA TE PONTA kWh 100,00 0,500000 50,00',
               'ENERGIA ELETRICA USD PONTA kWh 100,00 1,200000 120,00']
        rows=extract_billing_rows(pages,'danf3e')
        self.assertEqual(rows['te_ponta']['pagina'],2)
        self.assertEqual(rows['tusd_ponta']['pagina'],3)

    def test_cache_preserva_evidencias(self):
        # Teste de integração sem conexão real com Nextcloud.
        doc=pymupdf.open(); p=doc.new_page()
        p.insert_text((50,80),'DANF3E')
        p.insert_text((50,100),'NOTA FISCAL ELETRONICA DE ENERGIA ELETRICA')
        p.insert_text((50,130),'TOTAL 100,00 0,00')
        payload=doc.tobytes();doc.close()
        class ShareFake:
            def __init__(self,*a,**kw):pass
            def connect(self):pass
            def list_pdfs(self):return [{'relative':'teste.pdf','etag':'E1','size':len(payload)}]
            def download(self,item):return payload
        with tempfile.TemporaryDirectory() as td,patch.object(sync,'PublicShare',ShareFake),\
                patch.dict(os.environ,{'NEXTCLOUD_SHARE_TOKEN':'token_exemplo','NEXTCLOUD_SHARE_PASSWORD':'senha_teste','ENERGIA_ID_CHAVE':'chave_teste'}),\
                patch.object(sync,'DATA_FILE',Path(td)/'energia.json'),\
                patch.object(sync,'STATE_FILE',Path(td)/'estado.json'),\
                patch.object(sync,'STATUS_FILE',Path(td)/'status.json'),\
                patch.object(sync,'AUDIT_FILE',Path(td)/'auditoria.json'):
            n1=sync.scan()
            first=sync.read_json(Path(td)/'auditoria.json',{})['documentos']
            self.assertEqual(n1[1],1)
            self.assertTrue(all('campos' in v for v in first.values()))
            n2=sync.scan()
            second=sync.read_json(Path(td)/'auditoria.json',{})['documentos']
            self.assertEqual(n2[1],0)
            self.assertEqual(first,second)


class TestLoteRealQuandoDisponivel(unittest.TestCase):
    def test_zip_64_pdfs(self):
        import zipfile
        target=os.environ.get('COPEL_TEST_ZIP')
        if not target:self.skipTest('Defina COPEL_TEST_ZIP para habilitar validação dos 64 PDFs reais')
        archive=Path(target)
        if not archive.is_file():self.fail('COPEL_TEST_ZIP informado, mas arquivo não existe')
        with zipfile.ZipFile(archive) as z:
            names=[name for name in z.namelist() if name.lower().endswith('.pdf')]
            self.assertEqual(len(names),64)
            docs=[]
            for name in names:
                content=z.read(name)
                records=sync.parse_pdf_records(content)
                with pymupdf.open(stream=content,filetype='pdf') as pdf:
                    pages=[p.get_text(sort=True)+'\n'+p.get_text(sort=False)[:2500] for p in pdf]
                for record in records:
                    evidence,updates,issues=review_document(pages,record,'chave_teste')
                    self.assertEqual(issues,[],name+': '+str(issues))
                    self.assertIn(record['status'],('ok','parcial'),name)
                    self.assertNotIn('_uc', updates)
                    docs.append(record)
            self.assertEqual(len(docs),97)
            self.assertEqual(sum(d['status']=='parcial' for d in docs),36)
            self.assertEqual(sum(d['status']=='ok' for d in docs),61)
            self.assertTrue(all(d['consumo_kwh'] is None for d in docs if d['tipo_documento']=='historico_faturamento'))

if __name__ == '__main__':unittest.main()
