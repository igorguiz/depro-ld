# DEPRO-LD v1.1 — Etapa documental de empenhos

A atualização preserva a coleta cadastral da v1.0.1 e adiciona uma automação SEI independente. **Não é necessário apagar nenhum arquivo** do repositório `depro-ld`.

## Enviar/substituir no repositório `depro-ld`

- `index.html`: substituir o existente.
- `requirements.txt`: substituir o existente (acrescenta PyMuPDF).
- `scripts/atualizar_empenhos.py`: adicionar.
- `.github/workflows/consultar-empenhos-sei.yml`: adicionar, mantendo `.github/workflows/atualizar-e-publicar.yml`.
- `data/empenhos.json`: adicionar como placeholder inicial.
- `tests/test_empenhos.py`: opcional, para testes locais.

**Não substituir** `scripts/atualizar_contratos.py`: o pacote mantém a versão v1.0.1 com tentativas e timeout que já funcionou.

## Execução

1. GitHub → Actions → **Consultar empenhos SEI - ARCOLON** → Run workflow, branch `main`.
2. Abrir logs em **Consultar documentos publicos do SEI**. Confirmar o valor, número de documentos e eventuais erros.
3. O workflow grava `data/empenhos.json`; a página do GitHub Pages é republicada automaticamente.
4. Na aplicação, Gestão de Contratos → ARCOLON: aparecerá o bloco Empenhos se o JSON tiver sido validado.

## Semântica dos dados

O valor total da NE é calculado pelas operações de inclusão/reforço/anulação da versão MAIS RECENTE localizada no SEI. Versões antigas da mesma nota não são somadas.

Os documentos `Financeiro: Informações sobre o pagamento` podem vincular empenho a NF, OB, DR e OP, mas não substituem automaticamente um registro formal de liquidação. Assim, **saldo a liquidar permanece A apurar** até validação contábil. A rotina não deduz o valor das faturas do saldo de modo indevido.

O script exige PDF público, número do empenho e CNPJ/UG, registra problemas de leitura e preserva o JSON anterior quando não consegue localizar uma NE válida. Documentos integrais não são publicados; apenas metadados e URLs públicos.

**Limitação:** este é o primeiro levantamento de um único empenho. O processo pode conter versões e documentos adicionais; os resultados devem ser conferidos nos logs antes de considerar o valor atualizado.
