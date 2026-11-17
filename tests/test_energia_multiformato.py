"""Regression tests against locally supplied real Copel PDFs (when available)."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from sincronizar_energia import parse_pdf_records

SOURCES=Path('/mnt/data')
class TestRealCopelFormats(unittest.TestCase):
    def parse(self,name):
        path=SOURCES/name
        if not path.exists():self.skipTest('PDF local não incluído na versão distribuída')
        return parse_pdf_records(path.read_bytes())
    def test_relatorio_2018_2019_doze_meses(self):
        entries=self.parse('00 2018 a 03 2019-1.pdf')
        self.assertEqual(len(entries),12)
        self.assertEqual(len(set(e['mes_consumo'] for e in entries)),12)
        m={e['mes_consumo']:e for e in entries}
        self.assertEqual((m['2019-03']['consumo_kwh_ponta'],m['2019-03']['consumo_kwh_fora_ponta']),(4794,48024))
        self.assertEqual(m['2019-03']['valor_centavos'],4282974)
        self.assertEqual(m['2018-04']['valor_centavos'],4977667)
        self.assertTrue(all(r['status']=='parcial' for r in entries))
        self.assertTrue(all(r['tarifa_te_ponta'] is None for r in entries))
    def test_novembro_2021_legado(self):
        r=self.parse('02_ContaCopel-Nov_21.pdf')[0]
        self.assertEqual(r['mes_consumo'],'2021-10')
        self.assertEqual(r['valor_centavos'],3006459)
        self.assertEqual(r['demanda_contratada_kw'],300)
        self.assertEqual(r['consumo_kwh'],27918)
    def test_outubro_2022_ajuste_um_kwh(self):
        r=self.parse('13_ContaCopel-Out_22.pdf')[0]
        self.assertEqual(r['status'],'ok')
        self.assertEqual(r['mes_consumo'],'2022-10')
        self.assertEqual(r['consumo_kwh'],49962)
        self.assertEqual(r['consumo_kwh_ponta']+r['consumo_kwh_fora_ponta'],49961)
    def test_dezembro_2024_tarifas(self):
        r=self.parse('39_ContaCopel-Dez_24.pdf')[0]
        self.assertEqual(r['mes_consumo'],'2024-12')
        self.assertEqual(r['competencia_copel'],'2025-01')
        self.assertEqual(r['valor_reais'],31882.74)
        self.assertEqual(r['energia_injetada_kwh_fora_ponta'],15539)
        self.assertEqual(r['tarifa_te_ponta'],0.43489)
        self.assertEqual(r['tarifa_tusd_ponta'],1.2512)
        self.assertEqual(r['preco_faturado_te_fora_ponta'],0.370235)
    def test_junho_2026(self):
        r=self.parse('57_ContaCopel-Jun_26.pdf')[0]
        self.assertEqual(r['mes_consumo'],'2026-06')
        self.assertEqual(r['consumo_kwh'],39178)
        self.assertEqual(r['energia_injetada_kwh_fora_ponta'],13307)
        self.assertEqual(r['valor_centavos'],3476880)
        self.assertEqual(r['demanda_medida_kw'],143.64)

if __name__=='__main__':unittest.main()
