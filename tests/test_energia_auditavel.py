"""Testes da v1.7. PDFs reais opcionais; cenarios sinteticos sempre executados."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from copel_auditoria import normalize, decimal_pt, classify, nf3e_valid, nf3e_candidates, audit_lines, audit_total, review_document
from sincronizar_energia import parse_pdf_records

SOURCES=Path('/mnt/data')

class TestAuditoriaSempreExecutada(unittest.TestCase):
    def test_normalizacao_preserva_decimais(self):
        self.assertEqual(normalize('Energia Elétrica\u00a0  1.234,56'), 'ENERGIA ELETRICA 1.234,56')
        self.assertEqual(str(decimal_pt('1.234,56')),'1234.56')
    def test_layout_desconhecido(self):
        evidence,updates,warnings=review_document(['texto desconhecido'],{},'chave')
        self.assertEqual(updates['layout_detectado'],'layout_desconhecido')
        self.assertIn('layout_desconhecido',warnings)
    def test_danf3e_com_chave_invalida(self):
        a,u,w=review_document(['DANF3E\nNOTA FISCAL ELETRONICA DE ENERGIA ELETRICA\nChave de Acesso 9999 9999 9999 9999 9999 9999 9999 9999 9999 9999 9999'],{'valor_centavos':123,'consumo_kwh':100},'chave')
        self.assertIn('chave_nf3e_nao_identificada_ou_ambigua',w)
    def test_tabela_calculo_certo(self):
        page='DANF3E\nNOTA FISCAL ELETRONICA DE ENERGIA ELETRICA\nENERGIA ELETRICA TE PONTA kWh 100,00 0,500000 50,00'
        a,e=audit_lines([page,page],{'preco_faturado_te_ponta':0.5,'valor_te_ponta_reais':50},'danf3e')
        self.assertEqual(e,[])
        self.assertTrue(a['te_ponta']['validado'])
    def test_tabela_calculo_errado(self):
        page='ENERGIA ELETRICA TE PONTA kWh 100,00 0,500000 60,00'
        a,e=audit_lines([page,page],{},'danf3e')
        self.assertFalse(a['te_ponta']['validado'])
        self.assertIn('inconsistencia_aritmetica_te_ponta',e)
    def test_sem_inventar_valor_ausente(self):
        a,u,w=review_document(['NOTA FISCAL/CONTA DE ENERGIA ELETRICA\nVALORES FATURADOS'],{'valor_centavos':None,'consumo_kwh':None},'k')
        self.assertIn('total_sem_rotulo_confirmado',w)
    def test_total_faturado_divergente(self):
        first="DANF3E\nNOTA FISCAL ELETRONICA DE ENERGIA ELETRICA\nTOTAL 31.882,74 123,45"
        ev,issues=audit_total([first],{'valor_centavos':3188273},'danf3e')
        self.assertIn('total_diverge_do_cabecalho',issues)
        self.assertFalse(ev['validado'])
    def test_dv_chave_nf3e(self):
        def make43():
            return '41'+'2501'+'04368898000106'+'66'+'003'+'146620452'+'1'+'04397595' # 43?
        prefix=make43()
        self.assertEqual(len(prefix),43)
        valid=[]
        for last in '0123456789':
            key=prefix+last
            if nf3e_valid(key):valid.append(key)
        self.assertEqual(len(valid),1)
        self.assertTrue(nf3e_valid(valid[0]))
        self.assertEqual(nf3e_candidates('Chave de Acesso '+' '.join(valid[0][i:i+4] for i in range(0,44,4))),valid)

class TestAmostrasReais(unittest.TestCase):
    def test_documentos_reais(self):
        specs=[('00 2018 a 03 2019-1.pdf','historico_cmehfat0',12),
               ('02_ContaCopel-Nov_21.pdf','fatura_legada',1),
               ('13_ContaCopel-Out_22.pdf','danf3e',1),
               ('39_ContaCopel-Dez_24.pdf','danf3e',1),
               ('57_ContaCopel-Jun_26.pdf','danf3e',1)]
        import fitz
        for fname,layout,count in specs:
            path=SOURCES/fname
            if not path.exists():continue
            with self.subTest(fname=fname):
                b=path.read_bytes();records=parse_pdf_records(b)
                with fitz.open(stream=b,filetype='pdf') as doc:
                    pages=[p.get_text(sort=True)+'\n'+p.get_text(sort=False)[:2500] for p in doc]
                self.assertEqual(len(records),count)
                ev,_,warn=review_document(pages,records[0],'teste')
                self.assertEqual(ev['layout'],layout)
                self.assertEqual(warn,[])

if __name__=='__main__':unittest.main()
