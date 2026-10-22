# Gestão de Contratos - DEPRO-LD (v1.0)

**Projeto novo e independente** do PWA `gestao-contratos-utfpr` existente.

## Escopo da versão 1.0

- Tela inicial com duas entradas: **Gestão de Contratos** e **Gestão de Energia** (reservada).
- Ao abrir Gestão de Contratos, o usuário seleciona a empresa. Somente então os sete dados são mostrados.
- ARCOLON, contrato 18/2022, identificação interna Comprasnet 154227.
- Python extrai automaticamente os dados cadastrais de HTML público do Contratos.gov.br.
- O script valida número contratual, CNPJ, processo, vigência e valor. Em caso de falha **não substitui** o último arquivo de dados válido.
- GitHub Actions executa a consulta diariamente e grava `data/contratos.json` no repositório. GitHub Pages serve a página estática.

**Não inclui nesta etapa:** saldo de empenho, execução financeira, notas fiscais, autenticação, contratação de serviços, integração SEI ou CGU. O módulo Energia é somente uma área reservada.

Consulte `INSTALACAO.md` para a publicação.
