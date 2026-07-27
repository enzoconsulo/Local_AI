# Análise — ia-hibrida-limpa

## Visão geral
Ecossistema de **Data Warehouse + Conselho de Administração IA** para uma loja Shopee de
impressão 3D sob demanda (o dono, Enzo, é o único usuário). O sistema sincroniza catálogo,
pedidos, repasse (escrow) e sinais de pós-venda via API oficial da Shopee v2 e importa as
planilhas do Seller Center para um PostgreSQL; calcula o **lucro líquido real por variação**
(material + taxas + refugo) e roda auditorias de um "conselho" CFO/CMO/COO (via OpenAI) que
recomenda e — para ações seguras — executa mudanças na loja (preço, promoção, combo). A
interface é um app **Streamlit local**. Há ainda um módulo separado de geração de imagens
(`estudio_shopee`, via fal.ai) e um bootstrap legado de LLM local (`llm.py`, LiteLLM/RunPod)
que já saiu do fluxo principal.

## Arquitetura
O código real vive em `Local_AI/` (um repositório git próprio, aninhado neste projeto). O
app principal é `Local_AI/analista_dados_shopee/`:

- **`data_app.py`** — home do Streamlit: cartões de navegação e um status rápido do banco
  (contagem de produtos + última sync).
- **`pages/`** — 7 páginas Streamlit (só interface): `0 Visão Central` (KPIs, funil, boost,
  voucher, plano de ação — tudo local/grátis), `1 Engenharia de Fábrica`, `2 Sincronização`,
  `3 Cérebro IA` (auditoria OpenAI + atuador), `4 Chat Assistente` (text-to-SQL), `5
  Mapeamento Insumos`, `6 Lucro Real`.
- **`cerebro/`** — núcleo analítico, **sem Streamlit** (roda em CLI/testes também):
  - `config.py` — credenciais/modelos OpenAI por horizonte, sessão HTTP, caches em disco,
    vocabulário de ações, `VERSAO_PROMPT` (parte do fingerprint), `MigracaoPendenteError`.
  - `heuristicas.py` — camada determinística pura (âncora anti-alucinação): score de
    urgência, previsão 7d/30d, elasticidade, cluster, evidência, alertas e "alavancas".
  - `dossie.py` — extrai o DW com a `QUERY_DOSSIE` (janelas 7/30d sobre views) e monta o
    dossiê por variação, incluindo rateio híbrido de tráfego/ads e a "correlação profunda"
    (cesta, dia da semana, UF, margem de equilíbrio, curva ABC, pós-venda).
  - `memoria.py` — persistência analítica: fingerprint → cache semântico, checkpoint
    retomável por lote, avaliação de ações maduras (previsto vs. observado).
  - `motor_ia.py` — comunicação OpenAI (JSON mode): gatekeeper local, modo econômico, smart
    batching adaptativo, validação de completude e normalização defensiva da saída.
  - `atuador.py` — executa ações aprovadas na Shopee e grava o diário (`log_acoes_shopee`).
  - `orquestrador.py` — orquestra uma auditoria inteira (7d ou 30d), do dossiê à persistência.
  - `consultor.py` — motor do chat (página 4): text-to-SQL somente-leitura + resposta.
- **`workers/`** — ingestão de dados: `sync_catalogo`, `sync_pedidos` (pedidos + escrow),
  `sync_saude_conta` (saúde + views/curtidas via API), `sync_pos_venda` (rastreio,
  devoluções, promoções) e `importar_planilhas` (processa os exports do Seller Center).
- **`utils/`** — `db_pool.py` (pool psycopg2 thread-safe + helpers), `shopee_core.py` (motor
  da API Shopee v2: assinatura HMAC-SHA256, auto-renovação de token com lock, ações e
  consultas), `ui.py` (estilo/componentes), `padronizar_texto.py`.
- **`init_db/`** — `01_schema.sql` + migrações `02`..`17` + `aplicar_migrations.py` (runner
  idempotente com sondagem por objeto sentinela e registro em `sys_migrations`).
- **`docker-compose.yml`** — PostgreSQL 15 (porta host **5433**) + pgAdmin (5050).
- **`tests/`** — testes offline da camada determinística; **`run_local.ps1`** — script único
  que sobe o Docker, aplica migrações e abre o app.

Fora do app principal: `Local_AI/estudio_shopee/` (gerador de imagens Streamlit, deps
próprias) e `Local_AI/llm.py` (proxy LiteLLM legado — Groq/RunPod/Ollama).

## Fluxo de execução
1. **Subida:** `run_local.ps1` cria/valida o `CHAVES_DADOS.env`, sobe o Postgres no Docker,
   roda `aplicar_migrations.py` e executa `streamlit run data_app.py` (http://localhost:8501).
   Toda página e worker obtêm conexão pelo singleton de `utils/db_pool.get_connection()`.
2. **Ingestão (página 2 / workers):** a API (catálogo, pedidos+escrow, saúde, pós-venda) e o
   upload das planilhas populam as tabelas `dim_*`/`fato_*`; `shopee_core` cuida de
   assinatura e renovação do token; `importar_planilhas` protege contra arquivo repetido e
   períodos sobrepostos.
3. **Auditoria IA (página 3 → `orquestrador.executar_auditoria_por_horizonte`):**
   `dossie.gerar_dossie_produtos_com_memoria()` roda a `QUERY_DOSSIE`, aplica as heurísticas
   determinísticas e enriquece com a memória; então, na ordem de economia de custo:
   `avaliar_acoes_maduras` → `iniciar_ou_retomar_checkpoint` → `separar_resultados_reutilizaveis`
   (cache semântico por fingerprint) → `motor_ia.processar_em_lotes` (gatekeeper de produtos
   sem atividade → modo econômico para evidência baixa → lotes adaptativos →
   `chamar_cerebro_openai_preditivo` em JSON mode). A saída passa por `normalizar_saida_modelo`
   e `validar_sugestao_ia`, é persistida em `ia_execucoes_analiticas`/`ia_snapshots_variacao`
   e num cache em disco (`ultima_auditoria*.json`).
4. **Execução da ação:** aprovada na UI → `atuador.processar_acao_api` → `shopee_core`
   (`atualizar_preco_shopee` / `criar_promocao_shopee` / `criar_combo_shopee`) → registro em
   `log_acoes_shopee` vinculado à execução de origem (fecha o ciclo previsto vs. observado).
5. **Chat (página 4 → `consultor.executar_turno`):** o modelo gera uma query, o sistema a
   valida (`validar_sql_somente_leitura`) e executa em transação read-only, com 1 rodada de
   reparo, e devolve a resposta executiva. Máximo de 3 chamadas por turno.

## Stack e dependências
- **Linguagem/runtime:** Python **3.10+**; app web em **Streamlit** (multipage).
- **Banco:** **PostgreSQL 15** em Docker (imagem `postgres:15-alpine`), acessado via
  **`psycopg2-binary`** com `ThreadedConnectionPool`; a sessão força
  `timezone=America/Sao_Paulo` para as janelas 7d/30d não deslizarem à noite.
- **IA:** **OpenAI** por REST direto com **`requests`** (sem SDK) — `gpt-5.6-luna` (7d,
  reasoning low) e `gpt-5.6-terra` (30d, reasoning medium); JSON mode e `reasoning_effort`.
- **Shopee Open API v2:** `requests` + assinatura HMAC-SHA256 e auto-renovação de token
  (`shopee_core`).
- **Planilhas:** `pandas` + `openpyxl` (exports do Seller Center); `tabulate` para devolver
  tabelas ao chat. Utilitários: `python-dotenv`, `loguru`.
- **Módulo de imagens (`estudio_shopee`, à parte):** `streamlit`, `rembg`/U2-Net (remoção de
  fundo), `fal-client` (fal.ai), `Pillow`.
- **Legado (`llm.py`):** LiteLLM proxy sobre Groq/RunPod/Ollama — o `requirements.txt`
  registra que `litellm[proxy]` foi removido; o Cérebro passou a usar OpenAI direto.

## Pontos de atenção
- **Repositório git aninhado:** `Local_AI/` é um repo git próprio (com o histórico real das
  features) embutido em `ia-hibrida-limpa`, que o rastreia como um único gitlink. A gestão da
  fábrica (`_gestao/`) vive no repo externo, mas o código evolui no interno — atenção ao
  commitar/versionar (o pipeline da fábrica espera um repo por projeto).
- **Segredos em disco:** `analista_dados_shopee/CHAVES_DADOS.env` existe na árvore com chaves
  Shopee/OpenAI. Está coberto pelo `.gitignore` (`*.env`) e **não** é versionado (só o
  `.example`), mas continua presente localmente — não vazar.
- **Acoplamento forte ao schema (17 migrações):** o dossiê exige views/colunas específicas
  (migrações 12/15/17) e lança `MigracaoPendenteError`, chegando a bloquear a auditoria se
  faltarem. `aplicar_migrations.py` idempotente mitiga, mas é um pré-requisito rígido.
- **`QUERY_DOSSIE` monolítica:** uma única query com dezenas de CTEs (~560 linhas) é o coração
  e o ponto mais frágil do sistema; além disso, os **nomes de campo do dossiê são contrato**
  do fingerprint do cache, da UI e do prompt — renomear qualquer um invalida cache e pode
  reutilizar análise incompatível (por isso `VERSAO_PROMPT` precisa subir junto).
- **Cobertura de testes limitada:** `tests/` só cobre a camada determinística **offline**
  (`test_cerebro_correlacoes`, `test_importacao_csv`). Não há testes tocando banco, OpenAI,
  Shopee API, workers, `orquestrador` fim-a-fim ou UI; não há CI aparente. A robustez real
  depende das blindagens defensivas espalhadas no código (normalização de nulos, fallback de
  lote, escudo anti-alucinação de NULL vs. zero).
- **Ambiente "futuro/fictício":** modelos `gpt-5.6-*` e datas em 2026 são coerentes com a
  própria base (comentários, seed de sync em 26/01/2026); tratar como dados do projeto, não
  como erro.
- **Módulos periféricos com deps próprias:** `estudio_shopee` (rembg/fal-client) e `llm.py`
  (litellm) não estão no `requirements.txt` do app principal e precisam de instalação
  separada; o `estudio` roda de forma independente (`streamlit run app.py`).
- **Renovação de token de uso único:** `shopee_core` usa lock de arquivo + thread para evitar
  invalidar a cadeia de refresh quando dois processos renovam ao mesmo tempo — dependência
  sutil se o app for aberto em paralelo com um worker via CLI.

_Análise gerada em 2026-07-27 · commit d0b1cba_
