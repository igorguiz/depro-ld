"""Regressões de demanda v1.8.1, adaptadas à regra de injeção v1.8.2."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from copel_auditoria import extract_demand_measurements, extract_injection_measurements
from sincronizar_energia import parse_pdf_records

class TestDemanda(unittest.TestCase):
    def test_segunda_via_antes_do_rotulo(self):
        raw='Segunda Via DEMANDA USD 215 480 207,36 400,00 207,36 28,904755 5.993,69'
        parsed,evid,amb=extract_demand_measurements([raw])
        self.assertFalse(amb)
        self.assertEqual((parsed['medida'],parsed['contratada'],parsed['faturada']),(207.36,400,207.36))
    def test_sem_leituras_de_medidor(self):
        raw='DEMANDA USD 247,10 400,00 247,10 31,945730 7.893,79'
        parsed,evid,amb=extract_demand_measurements([raw])
        self.assertFalse(amb)
        self.assertEqual((parsed['medida'],parsed['contratada'],parsed['faturada']),(247.10,400,247.10))
    def test_nao_confundir_isenta_icms(self):
        parsed,evid,amb=extract_demand_measurements(['DEMANDA USD ISENTA ICMS 152,90 25,876063 3.956,45'])
        self.assertIsNone(parsed)
        self.assertFalse(amb)
    def test_nao_confundir_outra_demanda(self):
        parsed,evid,amb=extract_demand_measurements(['DEMANDA 240,40 400,00 240,40'])
        self.assertIsNone(parsed)
    def test_conflito_de_demanda(self):
        parsed,evid,amb=extract_demand_measurements([
            'DEMANDA USD 247,10 400,00 247,10',
            'DEMANDA USD 240,40 400,00 240,40'])
        self.assertTrue(amb)
        self.assertIsNone(parsed)

class TestInjecao(unittest.TestCase):
    def test_dois_postos_soma(self):
        a=extract_injection_measurements(['ENERGIA GERADA/INJETADA PONTA 76 76 0,00\nENERGIA GERADA/INJETADA FORA P 3190278 3295892 13307,00'])
        self.assertEqual(a['total'],13307)
        self.assertEqual(a['origem_total'],'soma_postos_medicao')
    def test_nao_inventar_ponta_zero(self):
        a=extract_injection_measurements(['ENERGIA GERADA/INJETADA FORA P 0 28593 15806,00'])
        self.assertIsNone(a['ponta'])
        self.assertIsNone(a['total'])
    def test_total_explicito_tem_prioridade(self):
        a=extract_injection_measurements(['ENERGIA GERADA/INJETADA TOTAL 0 300 300,00\nENERGIA GERADA/INJETADA FORA P 0 200 200,00'])
        self.assertEqual(a['total'],300)
        self.assertEqual(a['origem_total'],'total_explicito')
    def test_nao_duplicar_tributos(self):
        a=extract_injection_measurements(['ENERGIA ELETRICA TE F PONTA kWh 100 0,3 30,00\nENERGIA ELETRICA TUSD F PONTA kWh 100 0,4 40,00'])
        self.assertIsNone(a['total'])
    def test_marcadagua_pagina_nao_cruza_linhas(self):
        a=extract_injection_measurements(['ENERGIA GERADA/INJETADA PONTA\n75 76\nSegunda Via\nENERGIA GERADA/INJETADA FORA P 10 20 10,00'])
        self.assertIsNone(a['ponta'])
        self.assertIsNone(a['total'])

class TestPdfsReais(unittest.TestCase):
    def test_faturas_conhecidas(self):
        import zipfile
        source=Path('/mnt/data/Contas Copel.zip')
        if not source.exists():self.skipTest('ZIP original não disponível')
        expected={
            '29_ContaCopel-Fev_24.pdf':(207.36,400,207.36,24502),
            '38_ContaCopel-Nov_24.pdf':(247.10,400,247.10,15806),
            '57_ContaCopel-Jun_26.pdf':(143.64,345,143.64,13307),
        }
        with zipfile.ZipFile(source) as z:
            for filename, values in expected.items():
                name=next(n for n in z.namelist() if n.endswith(filename))
                record=parse_pdf_records(z.read(name))[0]
                actual=tuple(record[k] for k in ('demanda_medida_kw','demanda_contratada_kw','demanda_faturada_kw','energia_injetada_kwh'))
                self.assertEqual(actual,values,filename)

if __name__=='__main__':unittest.main()
