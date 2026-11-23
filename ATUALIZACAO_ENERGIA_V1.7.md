# Gestão de Energia DEPRO-LD — Extrator auditável v1.7 (copel-auditavel-5)

## Objetivo e cautelas

A versão 1.7 é **uma atualização incremental da v1.6**, exclusivamente para a coleta de dados. **Não altera o dashboard**. É necessário manter o workflow GitHub Actions e os Secrets já configurados. Os PDFs permanecem na Nuvem UTFPR; os JSON publicados são públicos. Não publicar token, senha, número real de UC, chave fiscal de 44 dígitos nem PDF original.

**Antes de atualizar:** baixe um backup do repositório e, em especial, de `data/energia.json`, `data/energia_estado.json` e `data/energia_status.json`. A versão reprocessará os PDFs por alteração de `extrator_versao` para `copel-auditavel-5`.

## Arquivos para copiar no repositório GitHub

- Substituir `scripts/sincronizar_energia.py`.
- Adicionar **novo** `scripts/copel_auditoria.py`.
- Adicionar `tests/test_energia_auditavel.py`.
- Manter `tests/test_energia_multiformato.py` (incluído no pacote para facilitar o teste).
- Adicionar este documento, se desejar.
- **Não** sobrescrever os JSON existentes com versões antigas.

## ALTERAÇÃO NECESSÁRIA NO WORKFLOW EXISTENTE

Em `.github/workflows/sincronizar-energia.yml`, na etapa que executa `git add`, adicionar `data/energia_auditoria.json` mantendo os outros três caminhos:

```bash
git add data/energia.json data/energia_estado.json data/energia_status.json data/energia_auditoria.json
```

O workflow recuperado para referência da versão v1.5.1 continha apenas os três primeiros arquivos. O workflow **real e atual do GitHub não foi inspecionado nesta execução**; modifique somente a linha `git add`, sem substituir as demais etapas.

## Alterações implementadas

1. **Layout identificado explicitamente:** CMEHFAT0, fatura antiga, DANF3E. Layout não reconhecido gera `conferencia` e `layout_desconhecido`.
2. **Normalização:** remoção de acentos e padronização dos espaços e caixa para comparação de rótulos. O texto original e as coordenadas permanecem disponíveis ao extrator anterior.
3. **Auditoria separada:** `data/energia_auditoria.json` contém, por registro, evidências do total, linhas TE/TUSD, chave da NF3e e avisos, sem expor o texto original.
4. **Validação financeira:** para linhas TE/TUSD reconhecidas, testa quantidade × preço ≈ valor, tolerância dependente das casas decimais da tarifa; compara também os preços e valores encontrados com os campos do extrator. O total é conferido contra a linha TOTAL (DANF3E) ou a seção Valor a Pagar (legado).
5. **NF3e:** reconhece os 44 dígitos mesmo quando o texto do cabeçalho está intercalado; valida dígito verificador módulo 11 e modelo 66; publica somente identificador HMAC `chave_nf3e_id` (não os 44 dígitos). Detecta a segunda via da mesma NF3e por esse identificador.
6. **Unidade consumidora:** identifica UC apenas quando aparece com âncora textual verificável no cabeçalho; usa HMAC estável com comprimento 12. Quando a UC não é identificável, registra `unidade: null`, sem presumir correspondência pela pasta.
7. **Conferência:** erro em linha aritmética, chave NF3e ausente/inválida, total divergente, campo essencial ausente ou layout desconhecido altera status para `conferencia`.
8. **Arquivos removidos:** mantém os registros antigos com `origem_removida: true` para rastreabilidade, mas não contabiliza esses registros como novas falhas de extração em `faturas_conferencia`.
9. **Históricos:** continuam `parcial`, com consumo ponta/fora e valor. Documentos históricos que possuem vários meses continuam gerando vários registros.
10. **Testes:** 14 testes locais passaram com os cinco PDFs de amostra; testes sintéticos de divergência financeira, chave inválida e layout desconhecido também passaram.

## Limitações conhecidas e trabalhos pendentes

- A rotina central de extração da v1.6 ainda contém alguns `regex` posicionais e coordenadas fixas no formulário histórico; a v1.7 **audita** os resultados, mas **não substituiu integralmente** esse mecanismo por reconhecimento geométrico de todas as tabelas.
- O teste da chave da NF3e verifica validade matemática, **não consulta autorização fiscal** na SEFAZ.
- O fechamento do total com *todas* as linhas de impostos, demanda, créditos e bandeiras ainda depende de uma tabela completa de rubricas. A v1.7 confere o total contra a seção de total, e cada linha TE/TUSD separadamente; **não** infere que a soma dessas quatro linhas iguala o total da fatura.
- Não foi adicionada dependência `pdfplumber`/`pdfminer` (segunda extração foi deliberadamente adiada).
- Não existem ainda 15–20 gabaritos homologados, apenas cinco PDFs reais de referência e testes sintéticos. A precisão da coleção inteira **não foi medida**.
- Códigos de UC distintos podem representar mudanças oficiais de numeração da mesma unidade; mapear equivalências exigirá documento ou configuração externa. A v1.7 não presume equivalência.
- A política de manter registros removidos para auditoria está preservada. Se desejar uma base pública somente com registros vigentes, será necessário separar um histórico de tombstones ou gerar uma visão consolidada sem removidos.
- O `energia.json` disponibilizado nesta conversa foi gerado **antes** da remoção de arquivos posteriores; os 63 PDFs atuais não estavam disponíveis para execução completa. **Os 14 testes não equivalem à homologação em produção**.

## Critérios de período definidos

- Abril/2018 a março/2021: registros `parcial` quando houver histórico disponível.
- Abril/2021 a agosto/2021: janela esperada sem dados; não criar registros zerados.
- Setembro/2021 em diante: faturas individuais, começando pela NF com referência outubro/2021 e leitura atual 30/09/2021.
- `mes_consumo` definido pela leitura atual nas faturas individuais; `competencia_copel` continua representando a referência de faturamento.

## Teste sugerido após atualização

1. Commit dos arquivos Python e dos testes.
2. Atualizar a linha `git add` no workflow, preservando as configurações atuais.
3. Executar GitHub Actions com `somente_teste_conexao` **desmarcado**.
4. Verificar `data/energia_status.json`, `data/energia_auditoria.json` e exemplos selecionados de `data/energia.json`.
5. Comparar os totais, consumo ponta e fora, demanda, TE/TUSD e chave fiscal dos PDFs reais com a saída JSON; inspecionar os alertas de `conferencia` antes de utilizá-los no dashboard.

## Rodar testes localmente (opcional)

`python -m unittest discover -s tests -v`

Os testes dos cinco PDFs são executados quando as amostras estão montadas em `/mnt/data`. Sem elas, esse conjunto é ignorado, e os testes sintéticos de auditoria continuam sendo executados.
