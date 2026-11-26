"""Regressão da energia injetada com zero inferido em layout individual reconhecido."""
from __future__ import annotations
import sys
import unittest
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from copel_auditoria import extract_injection_measurements, review_document
from sincronizar_energia import parse_pdf_records
import pymupdf as fitz

class TestRegraZeroInferido(unittest.TestCase):
    def test_danf3e_ausencia_ponta_inferir_zero(self):
        t='ENERGIA GERADA/INJETADA FORA P 0 28593 15806,00'
        r=extract_injection_measurements([t],'danf3e')
        self.assertEqual((r['ponta'],r['fora_ponta'],r['total']), (0,15806,15806))
        self.assertEqual(r['origem_ponta'],'zero_inferido_layout')
        self.assertEqual(r['origem_total'],'soma_postos_com_zero_inferido')
    def test_fatura_legada_com_fora_zero(self):
        r=extract_injection_measurements(['ENERGIA GERADA/INJETADA FORA P 0 0 0,00'],'fatura_legada')
        self.assertEqual((r['ponta'],r['fora_ponta'],r['total']), (0,0,0))
        self.assertEqual(r['origem_ponta'],'zero_inferido_layout')
    def test_historico_nao_inferir(self):
        r=extract_injection_measurements(['ENERGIA GERADA/INJETADA FORA P 0 5 5,00'],'historico_cmehfat0')
        self.assertIsNone(r['ponta']); self.assertIsNone(r['total'])
    def test_layout_desconhecido_nao_inferir(self):
        r=extract_injection_measurements(['ENERGIA GERADA/INJETADA FORA P 0 5 5,00'],'layout_desconhecido')
        self.assertIsNone(r['ponta']); self.assertIsNone(r['total'])
    def test_nenhum_posto_nao_inventar_zero(self):
        r=extract_injection_measurements(['ENERGIA ELETRICA CONSUMO 0 4 4,00'],'danf3e')
        self.assertIsNone(r['ponta']);self.assertIsNone(r['fora_ponta']);self.assertIsNone(r['total'])
    def test_ponta_explicita_prioritaria(self):
        r=extract_injection_measurements(['ENERGIA GERADA/INJETADA PONTA 1 5 4,00\nENERGIA GERADA/INJETADA FORA P 0 5 5,00'],'danf3e')
        self.assertEqual((r['ponta'],r['fora_ponta'],r['total']), (4,5,9))
        self.assertEqual(r['origem_ponta'],'medicao_explicita')
        self.assertEqual(r['origem_total'],'soma_postos_medicao')
    def test_total_explicito_divergente_nao_zerar(self):
        r=extract_injection_measurements(['ENERGIA GERADA/INJETADA TOTAL 0 11 11,00\nENERGIA GERADA/INJETADA FORA P 0 5 5,00'],'danf3e')
        self.assertIsNone(r['ponta']);self.assertIsNone(r['origem_ponta'])
        self.assertEqual(r['total'],11);self.assertEqual(r['origem_total'],'total_explicito')
    def test_total_explicito_igual_fora_ponta_zero(self):
        r=extract_injection_measurements(['ENERGIA GERADA/INJETADA TOTAL 0 5 5,00\nENERGIA GERADA/INJETADA FORA P 0 5 5,00'],'danf3e')
        self.assertEqual(r['ponta'],0);self.assertEqual(r['total'],5)
        self.assertEqual(r['origem_total'],'total_explicito')
    def test_duas_medicoes_fora_divergentes_nao_inferir(self):
        r=extract_injection_measurements(['ENERGIA GERADA/INJETADA FORA P 0 5 5,00\nENERGIA GERADA/INJETADA FORA P 0 6 6,00'],'danf3e')
        self.assertTrue(r['ambiguidade'])
        self.assertIsNone(r['ponta']);self.assertIsNone(r['total'])

class TestPdfsCompletos(unittest.TestCase):
    def test_lote_64_pdfs_e_28_pontas_inferidas(self):
        src=Path('/mnt/data/Contas Copel.zip')
        if not src.is_file(): self.skipTest('ZIP original indisponível')
        records=[]
        with zipfile.ZipFile(src) as archive:
            pdfs=[n for n in archive.namelist() if n.lower().endswith('.pdf')]
            self.assertEqual(len(pdfs),64)
            for n in pdfs:
                pdf=archive.read(n)
                entries=parse_pdf_records(pdf)
                with fitz.open(stream=pdf,filetype='pdf') as doc:
                    pages=[p.get_text(sort=True)+'\n'+p.get_text(sort=False)[:2500] for p in doc]
                for entry in entries:
                    ev, upd, problems = review_document(pages,entry,'chave_teste')
                    self.assertEqual(problems,[],f'{n}: {problems}')
                    entry.update(upd)
                    if entry['tipo_documento']=='historico_faturamento':
                        self.assertIsNone(entry['energia_injetada_kwh'])
                        self.assertIsNone(entry['origem_injecao_ponta'])
                    records.append(entry)
        self.assertEqual(len(records),97)
        individuals=[r for r in records if r['tipo_documento']=='fatura_individual']
        self.assertEqual(len(individuals),61)
        inferred=[r for r in individuals if r.get('origem_injecao_ponta')=='zero_inferido_layout']
        self.assertEqual(len(inferred),28)
        self.assertEqual(sum(r['layout_detectado']=='danf3e' for r in inferred),16)
        self.assertEqual(sum(r['layout_detectado']=='fatura_legada' for r in inferred),12)
        self.assertEqual(sum(r.get('origem_injecao_ponta')=='medicao_explicita' for r in individuals),33)
        self.assertTrue(all(r['energia_injetada_kwh'] is not None for r in individuals))
        self.assertTrue(all(r['energia_injetada_kwh']==r['energia_injetada_kwh_ponta']+r['energia_injetada_kwh_fora_ponta'] for r in individuals))
        self.assertEqual(sum(r['status']!='ok' for r in individuals),0)
        known={r['mes_consumo']:r for r in individuals}
        self.assertEqual((known['2024-11']['energia_injetada_kwh_ponta'], known['2024-11']['energia_injetada_kwh']), (0,15806))
        self.assertEqual((known['2024-12']['energia_injetada_kwh_ponta'], known['2024-12']['energia_injetada_kwh']), (0,15539))
        self.assertEqual(known['2026-06']['energia_injetada_kwh'],13307)
        self.assertEqual(known['2024-11']['consumo_kwh'],42600)
        self.assertEqual(known['2024-11']['validacao_campos']['energia_injetada_kwh_ponta'],'inferido_por_layout')
        self.assertEqual(known['2024-11']['validacao_campos']['energia_injetada_kwh'],'calculado_com_zero_inferido')
        self.assertEqual(known['2026-06']['validacao_campos']['energia_injetada_kwh'],'calculado_dos_postos_medidos')

if __name__=='__main__':unittest.main()
