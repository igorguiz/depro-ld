# DEPRO-LD — Gestão de Energia v1.6 (coleta e validação)

Esta versão NÃO reconstrói o dashboard. Atualiza o **extrator**, preservando o restante da aplicação.

## Arquivos a atualizar
- `scripts/sincronizar_energia.py` — extrator multiformato e sincronização WebDAV.
- `energy.js` — compatibilidade mínima: exibe meses pelo `mes_consumo` e aceita registros `parcial` nos totais, sem redesenhar a interface.
- `tests/test_energia_multiformato.py` — verificações de regressão (executam com os PDFs quando presentes localmente; PDFs não fazem parte da entrega).

Não substitua `data/energia.json`, `data/energia_estado.json` ou `data/energia_status.json` por exemplos. Os JSONs do ZIP são **arquivos iniciais antigos**, pois não temos acesso ao histórico atual do seu GitHub nesta conversa. **Seu histórico real deve ser preservado no repositório.**

## Instalação no GitHub, sem programa local
1. Faça backup em **Code → Download ZIP** no repositório `igorguiz/depro-ld`.
2. Carregue somente os três arquivos de código acima, respeitando suas pastas.
3. Faça o commit na branch `main`.
4. Em **Actions → Sincronizar faturas Copel na Nuvem UTFPR → Run workflow**, execute com `somente_teste_conexao` **desmarcado**.
5. Consulte `data/energia_status.json`, especialmente `faturas_processadas`, `faturas_parciais`, `faturas_conferencia`, `faturas_duplicadas` e `novos_ou_alterados`.
6. Examine amostras do `data/energia.json` e confira os campos. A versão do extrator mudou para `copel-multiformato-4`: isso força reprocessamento dos arquivos, mesmo sem alterações na nuvem.

## Regras adotadas
- `mes_consumo`: mês da **leitura atual** nas faturas individuais. `competencia_copel` preserva o mês/ano oficial da fatura.
- Relatório CMEHFAT0: cada PDF pode produzir várias referências mensais. `mes_consumo` usa a **referência do relatório**, pois não há datas das leituras.
- `parcial`: histórico com consumo na ponta/fora de ponta e valor total presentes. Ausências de TE/TUSD/datas de leitura permanecem `null`.
- Separação de TE, TUSD, preços unitários e valores do consumo por posto em faturas completas quando discriminados.
- Demanda medida, contratada, faturada; energia injetada por posto quando comprovada, sem duplicar créditos TE/TUSD.
- `valor_reais` (real) e `valor_centavos` (inteiro) são ambos mantidos para compatibilidade.
- PDFs e nomes dos arquivos não são publicados. A UC real não é publicada; apenas identificador pseudônimo. PDFs permanecem na Nuvem UTFPR.
- Documentos múltiplos do mesmo mês/UC: prioriza uma fatura individual sobre o relatório histórico, sinalizando o histórico como `duplicado`. Se houver mais de uma fonte equivalente, marca `conferencia`.
- Uma divergência de até 1 kWh entre a soma dos postos e o total do medidor é tolerada e preservada, sem alteração dos valores originais.
- A rotina usa somente leitura do WebDAV e mantém dados históricos se a consulta falhar. Para mais segurança, cadastre `ENERGIA_ID_CHAVE` como segredo fixo.

## Limitações e homologação
- O extrator foi testado com cinco PDFs reais fornecidos (quatro contas individuais e um relatório com 12 meses). Isso não garante leitura perfeita das 64 faturas da nuvem.
- **Não houve acesso real à Nuvem UTFPR nesta execução**. Execute o workflow no GitHub e confira o JSON produzido.
- Campos de tarifa em modelos antigos sem separação explícita TE/TUSD ficam `null`. Para 2018–2019 não estimamos tarifas, injeção solar nem datas de leitura.
- Embora os dados principais sejam de origem institucional, o GitHub Pages publica JSON acessível externamente. Confirme quais métricas podem ser publicadas conforme as normas internas.
