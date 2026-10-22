# DEPRO-LD v1.2 — instalação no repositório `depro-ld`

Preserva o PWA antigo, a identidade visual e `scripts/atualizar_contratos.py` v1.0.1.

1. Envie os arquivos do ZIP para os mesmos caminhos indicados, **substituindo** `index.html` e `scripts/atualizar_empenhos.py` e **adicionando** `scripts/importar_pagamentos.py`, `data/pagamentos.json` e `.github/workflows/consultar-pagamentos-v12.yml`.
2. O workflow `.github/workflows/consultar-empenhos-sei.yml` já está no repositório, portanto não é necessário substituí-lo.
3. Execute **Actions → Consultar empenhos SEI - ARCOLON → Run workflow** para levantar notas de empenho e vínculos documentais de pagamento de 2026.
4. Execute **Actions → Atualizar pagamentos ARCOLON (base conciliada) → Run workflow** para importar os pagamentos mensais públicos **já validados** no projeto original `gestao-contratos-utfpr`.
5. Confira a página em janela privativa: Gestão de Contratos → ARCOLON.

## Advertências importantes

- A tabela mensal **é alimentada temporariamente pelo JSON público do PWA original** (CGU + SEI); não é uma apuração exclusivamente pelo SEI. A classificação entre materiais e serviços permanece com aquela rotina auditada.
- **Somente dados de pagamentos de 2026** são exibidos. A importação preserva o JSON anterior caso a fonte remota falhe.
- Empenhos emitidos antes de 2026 exibem apenas saldo, marcado **A apurar**. Não publicamos um número negativo sem sua memória de cálculo: valores negativos de 'movimentação no exercício' não são o saldo contábil de restos a pagar.
- O valor de `2026NE000051` é buscado na última versão documental encontrada no SEI; o saldo continua A apurar até validação de liquidações, estornos e inscrição em RP.
- Os documentos de pagamento do SEI não trazem sempre data de OB nem a evidência contábil de liquidação; por isso o cálculo do saldo não deve ser presumido apenas das NFs.
- Se a página de contratos.comprasnet falhar com 500, a sincronização financeira é independente e os dados cadastrais anteriores ficam preservados.
