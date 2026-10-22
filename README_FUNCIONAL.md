# DEPRO-LD — integração funcional (layout aprovado v1.4)

Preserva a aparência da prévia aprovada, agora lendo `data/contratos.json`, `data/empenhos.json` e `data/pagamentos.json`. Os indicadores financeiros não são valores fictícios fixados no HTML.

## Instalação

No **novo** repositório `depro-ld`, mantenha a estrutura de pastas e envie todos os arquivos desta pasta. É seguro criar um backup primeiro. Não altere o projeto antigo `gestao-contratos-utfpr`.

**Actions a executar:**

1. `Atualizar Contratos.gov.br e publicar DEPRO-LD` para obter cadastro.
2. `Consultar empenhos SEI - ARCOLON` para obter NEs de 2026 e documentos financeiros.
3. `Atualizar pagamentos ARCOLON (base conciliada)` para importar as notas e valores do PWA anterior.

Observe que o importador de pagamentos ainda depende do resumo público conciliado do projeto anterior. Não é uma migração independente da CGU/SEI. Os números fiscais dependem da existência de `numero_nf`/`nota_fiscal` (ou campos equivalentes) na origem; em caso de ausência, a tabela informa que não foram identificados.

**Vigência**: limite R$ 359.239,58 para 25/07/2026–25/07/2027. O saldo será apresentado como **A apurar** se faltarem datas individuais; não se pode alocar integralmente o mês julho sem verificar a data. Mesmo com datas, confirme a completude da fonte.

**Empenhos**: só aparecem NEs emitidas no exercício corrente na UG 150148. Saldo contábil não é derivado simplesmente da soma de notas fiscais.

**Segurança**: não subir credenciais nem PDFs pessoais ao repositório público.
