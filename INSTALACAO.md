# Instalação do novo DEPRO-LD no GitHub (passo a passo)

1. **Não altere o repositório antigo** `gestao-contratos-utfpr`.
2. No GitHub, clique em **New repository** e crie, por exemplo, `depro-ld` (de preferência público para GitHub Pages no plano gratuito). **Não inicialize com README**, para facilitar o envio.
3. Descompacte o ZIP fornecido. Envie o **conteúdo interno** de `depro_ld_v1_completo/` à raiz do repositório novo, preservando a estrutura e o diretório oculto `.github/workflows/`. Confira que `index.html`, `contratos.json`, `requirements.txt` estão na raiz, `scripts/atualizar_contratos.py` em `scripts/`, e o `.yml` em `.github/workflows/`.
4. Faça **Commit changes** na branch `main`.
5. Vá a **Settings → Actions → General → Workflow permissions** e selecione **Read and write permissions**, se essa opção estiver disponível. Salve. O workflow precisa ter permissão para gravar o JSON gerado. Se a organização restringir essa configuração, use um token de ação autorizado conforme a política institucional.
6. Vá a **Actions**, selecione **Atualizar Contratos.gov.br e publicar DEPRO-LD**, clique **Run workflow** e confirme a branch `main`.
7. Confirme nos logs `OK: 18/2022 ...` e a existência do arquivo `data/contratos.json` com valores reais. Se houver erro de estrutura HTML ou bloqueio do servidor, o fluxo falha sem publicar dados novos.
8. Vá a **Settings → Pages → Build and deployment**, selecione **Deploy from a branch**, branch **main**, pasta **/(root)** e salve.
9. Acesse `https://SEU_USUARIO.github.io/depro-ld/` (substituindo o usuário e o nome real do novo repositório). A publicação do Pages pode depender do workflow próprio do GitHub.
10. Na página inicial, clique em **Gestão de Contratos** → **Selecione a empresa** → **ARCOLON**. Verifique os sete dados e a data da consulta. Clique em Gestão de Energia para ocultar o painel de contratos.

## Notas

- O arquivo `data/contratos.json` começa vazio intencionalmente; os valores surgem somente após a primeira execução bem-sucedida do workflow.
- Não copie a chave `CGU_API_KEY`: a versão 1.0 não utiliza CGU ou credenciais.
- Teste local: `python -m pip install -r requirements.txt` e `python -m unittest discover -s tests -v` e, para consultar, `python scripts/atualizar_contratos.py`. Para testar a interface localmente, utilize `python -m http.server 8000` em vez de abrir o HTML via `file://`.
- GitHub Pages é público: publique somente informações contratuais públicas. Não inclua documentos sigilosos nem credenciais no repositório.
