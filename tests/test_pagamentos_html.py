import sys,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import atualizar_empenhos as e
from bs4 import BeautifulSoup

PAY='<html><body><h2>INFORMAÇÕES SOBRE O PAGAMENTO</h2><table><tr><td>Nota de Empenho (NE)</td><td>Financeiro: Nota de Empenho 150148/2026NE000051 (SEI nº 5558139)</td></tr><tr><td>Ordem de Pagamento (OP)</td><td>150148/2026OP002039 - 15358,95</td></tr><tr><td>Ordem Bancária (OB)</td><td>150148/2026OB002038</td></tr><tr><td>Documento de Arrecadação</td><td>150148/2026DR800078 - 663,51</td></tr><tr><td>Nota Fiscal</td><td>Nota Fiscal 255 : Ref. a Serviços (5878873) Nota Fiscal 305 : Ref. Materiais (5878881)</td></tr></table></body></html>'
class Tests(unittest.TestCase):
 def test_internal_html_payment(self):
  result=e.extract_document(SimpleNamespace(content=PAY.encode(),headers={'Content-Type':'text/html; charset=utf-8'},text=PAY))
  doc=e.parse_any_payment(result)
  self.assertEqual(doc['empenho'],'2026NE000051')
  self.assertEqual(doc['ordem_bancaria'],'2026OB002038')
  self.assertEqual(len(doc['notas']),2)
  self.assertEqual(doc['retencao_centavos'],66351)
 def test_discover_internal_payment(self):
  label='Financeiro: Informações sobre o pagamento 5882268'
  h='<table><tr><td><a onclick="window.open(\'md_pesq_documento_consulta_externa.php?abc=xyz\')">'+label+'</a></td></tr></table>'
  d=e.discover(h)
  self.assertEqual(d[0]['sei'],'5882268')
  self.assertEqual(d[0]['tipo'],'pagamento')
if __name__=='__main__':unittest.main()
