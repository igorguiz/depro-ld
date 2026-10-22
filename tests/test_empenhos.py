import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import atualizar_empenhos as e

class TestEmpenhos(unittest.TestCase):
    def test_money(self):
        self.assertEqual(e.cents('85.000,12'),8500012)
    def test_ne(self):
        text='''Nota de Empenho\n150148\n2026 NE 51\n82.395.773/0001-89\nLista de Itens\nTotal da Lista\n85.000,12\n09/03/2026 Inclusão 1,18610 28.665,3730 34.000,00\n06/05/2026 Reforço 1,77915 28.665,3730 51.000,00\n23/09/2026 Reforço 1,00000 0,1200 0,12\nAssinaturas\nVersão Data/Hora Operação\n009 25/09/2026 13:17 Alteração'''
        n=e.parse_ne(text)
        self.assertEqual(n['valor_total_centavos'],8500012)
        self.assertEqual(n['versao'],9)
    def test_pagamento(self):
        text='''INFORMAÇÕES SOBRE O PAGAMENTO\n150148/2026NE000051\n150148/2026OP002039 - 15358,95\n150148/2026OB002038\n150148/2026DR800078 - 663,51\nNota Fiscal 255 : Ref. a Serviços (5878873)\nNota Fiscal 305 : Ref. Materiais (5878881)'''
        p=e.parse_payment(text)
        self.assertEqual(p['ordem_bancaria'],'2026OB002038')
        self.assertEqual(len(p['notas']),2)
        self.assertEqual(p['retencao_centavos'],66351)
if __name__=='__main__':unittest.main()
