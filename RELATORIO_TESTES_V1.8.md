# Relatório de validação — Copel v1.8 — 23/11/2026

## Dados disponibilizados pelo usuário

- Arquivo `Contas Copel.zip`: 64 PDFs (3 relatórios históricos de 12 meses + 61 faturas individuais).
- JSONs de 23/11/2026: `energia.json`, `energia_estado.json`, `energia_status.json`, `energia_auditoria.json`.
- PDF adicional de exemplo: `00 2022 a 03 2023.pdf`, não incluído no ZIP de 64 arquivos.
- CSV de comparação elaborado a partir dos PDFs na auditoria anterior, usado como referência independente para os 61 documentos individuais.

## Resultado de validação

- 23 testes automatizados passaram com `COPEL_TEST_ZIP` configurado para os 64 PDFs.
- 97 registros mensais no lote de 64 PDFs: 36 `parcial` e 61 `ok`.
- 0 alertas de auditoria nesse lote, 0 divergências dos campos comparados nos 61 documentos individuais.
- O teste de 61 documentos compara diretamente mês de leitura, consumo medido, valores totais, demanda, quantidades por posto e valores/preços das rubricas documentais. O teste de 36 históricos confirma extração, classificação `parcial` e ausência de total artificial.
- A rotina de cache foi verificada para preservar auditoria previamente gerada.
- As regras de exclusão de `_uc` real foram verificadas no código.

## Limitação interpretativa

Nenhum desses testes autoriza prometer software 'sem falhas'. A comparação independente é uma aferição automatizada, não uma homologação manual de todas as rubricas dos 64 PDFs. Layouts futuros podem mudar. Os campos ausentes por fonte devem permanecer `null`.

## Arquivos de teste (não publicar os PDFs)

A bateria de regressão está em `tests/test_energia_v18.py`. As faturas completas, chaves fiscais de 44 dígitos e credenciais não estão incluídas no ZIP da atualização.
