import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from atualizar_contratos import extract

CFG={'id':'arcolon','id_comprasnet':154227,'numero':'18/2022','cnpj':'82.395.773/0001-89'}
HTML='''<table><tr><td>Número Contrato</td><td>00018/2022</td></tr>
<tr><td>Fornecedor</td><td>82.395.773/0001-89 - ARCOLON REFRIGERACAO INDUSTRIAL E COMERCIAL LTDA</td></tr>
<tr><td>Processo</td><td>23064.029408/2022-38</td></tr>
<tr><td>Vig. Início</td><td>25/07/2022</td></tr><tr><td>Vig. Fim</td><td>25/07/2027</td></tr>
<tr><td>Situação</td><td>Ativo</td></tr><tr><td>Valor Global ⓘ</td><td>R$ 1.293.713,52</td></tr></table>'''
class Teste(unittest.TestCase):
    def test_ok(self):
        d=extract(HTML, CFG)
        self.assertEqual(d['numero'],'18/2022')
        self.assertEqual(d['valor_global'],'R$ 1.293.713,52')
    def test_cnpj_indevido(self):
        with self.assertRaises(ValueError):extract(HTML.replace('82.395.773/0001-89','25.201.004/0001-69'),CFG)
    def test_campo_ausente(self):
        with self.assertRaises(ValueError):extract(HTML.replace('Vig. Fim','Nada'),CFG)
if __name__=='__main__':unittest.main()
