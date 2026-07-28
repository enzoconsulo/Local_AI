# ia-hibrida-limpa

Data Warehouse + "Conselho de Administração IA" para uma loja Shopee de impressão 3D sob
demanda, mais um Estúdio de imagens/anúncios com IA. Único usuário: Enzo.

Este projeto faz parte da fábrica Gerador_de_projetos. Gestão (especificação, plano,
tarefas, decisões) em `_gestao/`; o protocolo de tarefas está em
`../../_sistema/PROTOCOLO_TAREFAS.md`. Trabalhe em português (BR). Projeto **importado**
de uma pasta já existente (não passou por `/novo-projeto`) — `_gestao/ANALISE.md` documenta
a arquitetura herdada; `_gestao/ESPECIFICACAO.md`/`PLANO.md` cobrem só a feature nova em
andamento (anúncio completo no Estúdio).

## Stack
- Python 3.10+, dois apps **Streamlit** independentes (sem framework web/API REST próprio).
- `analista_dados_shopee`: **PostgreSQL 15** em Docker (`psycopg2-binary`), OpenAI REST
  direto (`requests`, sem SDK) em JSON mode, Shopee Open API v2 (HMAC-SHA256), `pandas`.
- `estudio_shopee`: `rembg`/U2-Net (remoção de fundo), `fal-client` (edição de imagem),
  LiteLLM local → Groq (instrução de edição), e agora também OpenAI REST direto para o
  anúncio (mesmo padrão do app principal, módulo `gerador_anuncio.py`).
- Sem CI. Sem framework de teste único — `analista_dados_shopee` usa scripts próprios em
  `tests/`; `estudio_shopee` ainda não tem suíte automatizada (ver Armadilhas).

## Como rodar
- App principal: a partir de `Local_AI/`, `powershell -ExecutionPolicy Bypass -File
  .\run_local.ps1` (sobe Docker + Postgres, aplica migrações, abre
  `streamlit run data_app.py` em http://localhost:8501). Detalhes/variáveis:
  `Local_AI/analista_dados_shopee/README.md`.
- Estúdio: `cd Local_AI/estudio_shopee && streamlit run app.py`. Segredos em
  `Local_AI/CHAVES.env` (ver `Local_AI/CHAVES.env.example`: `FAL_KEY`, `OPENAI_API_KEY`,
  `OPENAI_MODEL_ANUNCIO`, `GROQ`, `RUNPOD_KEY`, etc.).

## Como testar
- `analista_dados_shopee`: testes offline em `Local_AI/analista_dados_shopee/tests/`
  (camada determinística — heurísticas, importação de CSV; não toca banco/OpenAI/Shopee
  reais). Ambiente Python isolado próprio do módulo (não assuma `pytest` global instalado).
- `estudio_shopee`/`gerador_anuncio.py`: sem suíte automatizada ainda (T-005, backlog).
  Validação até aqui é manual, com a chamada HTTP sempre mockada (nunca gaste
  `OPENAI_API_KEY` real em teste) — ver Notas de execução de T-001/T-002.

## Arquitetura em 1 minuto
- **`Local_AI/`** — submódulo git PRÓPRIO (repo separado, branch `main`,
  `git@github.com:enzoconsulo/Local_AI.git`) onde o código de verdade vive; este repo
  externo (`ia-hibrida-limpa`, branch `master`) só rastreia o ponteiro do submódulo + a
  gestão da fábrica. Ver Armadilhas — isso muda o fluxo normal de commit do executor.
  - **`analista_dados_shopee/`** — app principal. `data_app.py` (home) + `pages/` (7
    páginas Streamlit); `cerebro/` é o núcleo analítico sem Streamlit (`dossie.py` monta o
    dossiê via `QUERY_DOSSIE`, `motor_ia.py` fala com OpenAI, `atuador.py` executa ações
    aprovadas na Shopee, `orquestrador.py` costura tudo); `workers/` ingere dados da API e
    das planilhas do Seller Center; `utils/` tem o pool de conexão e o motor da Shopee API
    (`shopee_core.py`); `init_db/` traz 17 migrações + runner idempotente.
  - **`estudio_shopee/`** — módulo de imagens à parte. `app.py` é a UI Streamlit inteira
    (upload, canvas, edição via fal.ai, aprovação); `gerador_anuncio.py` é o motor (sem
    Streamlit, testável isolado) da feature nova de anúncio: `chamar_openai_visao`
    (plumbing HTTP, T-001) e `gerar_anuncio_shopee` (prompt de copywriting + validação de
    schema, T-002) — ainda não chamado por nenhum botão da UI (T-003 pendente).
- **`_gestao/`** (neste repo externo) — especificação/plano/decisões/tarefas da fábrica.

## Convenções
- Todo texto voltado ao usuário final (anúncio, prompts de copywriting) em português (BR);
  o prompt de EDIÇÃO de imagem do Estúdio (`DIRETRIZES_SISTEMA` em `app.py`) é em inglês de
  propósito (exigência do motor fal.ai) — não confundir os dois.
- Módulos de IA (`cerebro/motor_ia.py`, `estudio_shopee/gerador_anuncio.py`) nunca deixam
  subir exceção crua de `requests`/`json` — sempre exceção própria com mensagem clara
  (`MigracaoPendenteError`, `ErroGeracaoAnuncio`), `raise ... from e` preservando a causa.
- `estudio_shopee` e `analista_dados_shopee` são módulos independentes por decisão
  explícita (`_gestao/DECISOES.md`): nenhum importa do outro, cada um com seu próprio
  arquivo de segredos (`CHAVES.env` vs. `CHAVES_DADOS.env`), mesmo repetindo o padrão de
  integração OpenAI. Não crie acoplamento novo entre eles.
- Chamada de IA paga é sempre por ação explícita do usuário (botão) — nunca automática.

## Armadilhas conhecidas
- **`Local_AI` é um git submodule real**, não uma pasta comum: código novo é commitado
  DENTRO de `Local_AI/` (branch `main`, remoto próprio) e o repo externo
  `ia-hibrida-limpa` recebe, num commit separado, só o ponteiro atualizado do submódulo +
  o arquivo da tarefa. Confirme com `git -C Local_AI log`/`git -C Local_AI status` além do
  `git status` da raiz do projeto.
- **`QUERY_DOSSIE` monolítica** (~560 linhas, dezenas de CTEs) é o coração e o ponto mais
  frágil do app principal; nomes de campo do dossiê são contrato do fingerprint de cache —
  renomear qualquer um invalida cache/prompt (por isso `VERSAO_PROMPT` sobe junto).
  Acoplamento rígido a 17 migrações; `dossie.py` lança `MigracaoPendenteError` se faltar
  alguma — rode `aplicar_migrations.py` (o `run_local.ps1` já faz isso).
- **Cobertura de testes é parcial:** `analista_dados_shopee/tests/` só cobre a camada
  determinística offline; nada toca banco/OpenAI/Shopee/UI real, e não há CI. A feature de
  anúncio do Estúdio (`gerador_anuncio.py`) ainda não tem NENHUMA suíte automatizada — só
  validação manual registrada nas tarefas T-001/T-002.
- **Feature de anúncio incompleta:** o backend (`gerar_anuncio_shopee`) já existe e foi
  validado manualmente, mas não está integrado à UI — não documente/anuncie a feature como
  utilizável de ponta a ponta até T-003/T-004 saírem do backlog.
- **Segredos em disco:** `CHAVES.env`/`CHAVES_DADOS.env` reais nunca são versionados (só
  os `.example`) mas existem localmente na árvore — não vazar em log/print/commit.
- **Ambiente "futuro/fictício":** modelos `gpt-5.6-*` e datas em 2026 são coerentes com a
  base do projeto (não é erro de digitação).
