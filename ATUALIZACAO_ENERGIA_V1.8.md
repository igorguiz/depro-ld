# DEPRO-LD / UTFPR — Atualização Gestão de Energia Copel v1.8

**Data:** 23/11/2026  
**Extrator:** `copel-auditavel-6`  
**Escopo:** apenas importação, validação e auditoria dos PDFs; **sem alterações no dashboard**.

## Como instalar no GitHub pelo navegador

Antes, faça backup dos arquivos atuais do repositório. Na página do GitHub `igorguiz/depro-ld`, substitua **estes dois arquivos** pelos que estão nas mesmas pastas deste pacote:

1. `scripts/sincronizar_energia.py`
2. `scripts/copel_auditoria.py`

Adicione ou substitua **estes três arquivos de teste** em `tests/`:

3. `tests/test_energia_auditavel.py` (mantido da versão anterior)
4. `tests/test_energia_multiformato.py` (mantido da versão anterior)
5. `tests/test_energia_v18.py` (**novo**, contém testes específicos)

Não é necessário alterar novamente `.github/workflows/sincronizar-energia.yml`, **desde que** você já tenha acrescentado `data/energia_auditoria.json` ao `git add` na versão 1.7. Confira se a etapa de publicação contém os quatro arquivos:

```bash
git add data/energia.json data/energia_estado.json data/energia_status.json data/energia_auditoria.json
```

**Não copie nenhum JSON antigo do pacote para o GitHub e não publique o ZIP das contas/PDFs originais.** Eles permanecem somente na Nuvem UTFPR. Não altere os GitHub Secrets: `NEXTCLOUD_SHARE_TOKEN`, `NEXTCLOUD_SHARE_PASSWORD` e `ENERGIA_ID_CHAVE` (se existir).

Em **Actions → Sincronizar faturas Copel na Nuvem UTFPR → Run workflow**, execute com `somente_teste_conexao` **desmarcado**. A primeira execução reprocessará todos os PDFs porque mudou a versão do extrator. Nas seguintes, PDFs sem alteração poderão ser recuperados do cache, preservando a evidência anterior da auditoria.

Confira, em `data/`: `energia_status.json`, `energia_auditoria.json`, `energia.json` e `energia_estado.json`.

## Regras técnicas implementadas

- **Consumo total:** `consumo_kwh` é extraído da linha documental de medição **ENERGIA ELETRICA CONSUMO**. Não é calculado pela soma das grandezas na ponta e fora de ponta. Se a leitura explícita estiver ausente ou ambígua, o registro individual entra em `conferencia`.
- **Consumos por posto:** `consumo_kwh_ponta` e `consumo_kwh_fora_ponta` são extraídos das rubricas específicas. As quantidades TE e TUSD não são somadas entre si.
- **Energia injetada:** mantemos os valores documentais por posto; `energia_injetada_kwh` só recebe um número quando houver campo total **expressamente identificado** no PDF. Na amostra atual, os totais são `null`, mesmo que haja leituras de injeção fora de ponta. Não atribuir zero quando o dado é ausente.
- **Históricos CMEHFAT0:** `parcial` é uma condição esperada. Não exigir TE/TUSD e leitura exata. O campo `consumo_kwh` fica `null` quando a coluna total de quantidade de consumo não traz um valor, mesmo quando os dois postos estão disponíveis. Demanda, valores e postos são preservados quando encontrados no documento.
- **Faturas legadas:** as linhas `ENERGIA ELET CONSUMO PTA`/`F PTA` não são falsamente classificadas como TE. Os montantes e preços são registrados nos novos campos `valor_energia_legada_ponta_reais`, `preco_energia_legada_ponta`, `valor_energia_legada_fora_ponta_reais` e `preco_energia_legada_fora_ponta`. Os campos de TE/TUSD permanecem `null` nesse layout.
- **DANF3E:** as quatro linhas TE/TUSD podem aparecer em qualquer página. Quantidade, preço e valor são extraídos preferencialmente da tabela fiscal e, se necessário, do extrato técnico. Quando uma linha existe no PDF e o JSON não a contém, a auditoria informa `campo_presente_na_fatura_mas_ausente_no_json_...` e a fatura entra em `conferencia`.
- **Tarifas reguladas:** TE/TUSD em `Informações Suplementares` são coletadas em todas as páginas que apresentarem a seção. Agregados de tarifa/preço não informados explicitamente continuam `null`.
- **Validação:** cada rubrica reconhecida deve satisfazer quantidade × preço ≈ valor, considerando arredondamento do preço publicado. O total da fatura é conferido com a respectiva seção de fechamento; não é exigido que apenas as quatro rubricas TE/TUSD somem o total da nota.
- **Identidade fiscal:** a chave NF3e é conferida por módulo 11 e a identidade é publicada somente como HMAC (`chave_nf3e_id`); não são publicados seus 44 dígitos.
- **Privacidade:** `'_uc'` — caso exista no resultado intermediário ou em dados antigos — é eliminado antes de salvar `energia.json` (inclusive registros com origem removida). A unidade pública é um identificador pseudonimizado.
- **Auditoria diária:** ao reutilizar um PDF do cache, a versão 1.8 mantém o registro de evidências em `energia_auditoria.json`; a v1.7 o substituía por um simples marcador de cache.
- **Período:** as faturas individuais usam a **data da leitura atual** quando ela existe, e preservam separadamente `competencia_copel`; históricos sem datas usam a referência histórica. Não preencher meses faltantes com zero.

## Resultados da simulação com os PDFs recebidos

Foi realizado um teste **local**, sem acesso à Nuvem UTFPR, usando os 64 PDFs do ZIP enviado pelo usuário em 23/11/2026, além de confrontar as 61 faturas individuais com a comparação independente anteriormente extraída dos próprios PDFs.

| Métrica | Resultado local |
|---|---:|
| PDFs | 64 |
| Meses/documentos históricos (`parcial`) | 36 |
| Faturas individuais (`ok`) | 61 |
| Registros mensais ativos | 97 |
| Sinalizações `conferencia` nesse lote | 0 |
| Alertas no relatório desse lote | 0 |
| Divergências nos campos confrontados das 61 faturas individuais | 0 |
| Testes automatizados executados com o ZIP real disponível | 23, todos passaram |

Exemplo: **novembro/2024** → `consumo_kwh=42600`, `consumo_kwh_ponta=8832`, `consumo_kwh_fora_ponta=33766`. O valor 42.600 vem diretamente da medição; 42.598 **não** substitui o total informado pela Copel.

O arquivo adicional `00 2022 a 03 2023.pdf` — **separado dos 64 da Nuvem UTFPR** — também foi testado como relatório histórico de 12 referências. Ele contém uma referência 09/2022, mas não foi incluído automaticamente na base ativa, pois isso dependeria de acrescentá-lo ao compartilhamento e reconciliar períodos já cobertos por faturas individuais.

## Pontos que NÃO podem ser declarados homologados

- **Não existe garantia matemática de ausência total de erros.** A auditoria completa ainda requer conferência humana por amostragem e gabaritos de referência efetivamente homologados; 23 testes automatizados e 64 documentos processados não provam exatidão em formatos futuros.
- O relatório histórico ainda depende de coordenadas de leitura vetorial de layouts CMEHFAT0. Outros templates históricos poderão exigir revisão.
- A chave NF3e é validada matematicamente, mas **não é consultada na SEFAZ** para verificar autorização fiscal.
- A decomposição de todas as rubricas financeiras da fatura e o fechamento independente do total não foi completamente modelada. Confirma-se o total informado e a matemática das linhas TE/TUSD presentes.
- Não há segundo extrator independente; a decisão foi adiar `pdfplumber`/`pdfminer` até verificar se os testes exigem esse recurso.
- A janela sem faturas confirmada pela documentação ativa é abril–agosto/2021; **setembro/2022 permanece ausente** na pasta de 64 PDFs. Não estimar nem preencher automaticamente. O histórico adicional de 2022–2023 poderá ser tratado separadamente se for autorizado.
- Na base já publicada, há 24 registros de origens removidas; o sincronizador preserva tais registros com `origem_removida: true` para rastreabilidade, mas os exclui da contagem de faturas processadas. Interfaces devem filtrar esse marcador.
- O sistema online só será considerado atualizado após executar e verificar o GitHub Actions. Os testes deste pacote são locais e não modificaram o repositório.

## Testes para quem tem ambiente Python (opcional)

```bash
python -m unittest discover -s tests -v
```

Para testar **todos os 64 PDFs reais** sem publicá-los no GitHub:

```bash
COPEL_TEST_ZIP="/caminho/Contas Copel.zip" python -m unittest discover -s tests -v
```

Em Windows PowerShell: `$env:COPEL_TEST_ZIP="C:\\caminho\\Contas Copel.zip"` seguido do comando `python -m unittest discover -s tests -v`.

Para o usuário final, **não é necessário executar Python no PC**. Basta substituir os arquivos pelo navegador e disparar o GitHub Actions.
