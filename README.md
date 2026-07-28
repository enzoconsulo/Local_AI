# ia-hibrida-limpa

Data Warehouse + "Conselho de Administração IA" para uma loja Shopee de impressão 3D sob
demanda (Enzo é o único usuário). O código de verdade vive em `Local_AI/` — um **submódulo
git próprio** (repositório separado, `git@github.com:enzoconsulo/Local_AI.git`, branch
`main`) — importado para dentro desta fábrica; a gestão (`_gestao/`) vive no repositório
externo `ia-hibrida-limpa`.

Este projeto tem dois apps Streamlit independentes:

- **`Local_AI/analista_dados_shopee/`** — o app principal: sincroniza catálogo, pedidos e
  repasse (escrow) via API Shopee v2, importa planilhas do Seller Center, calcula lucro
  líquido real por variação e roda auditorias de IA (CFO/CMO/COO via OpenAI) que
  recomendam e — para ações seguras — executam mudanças na loja (preço, promoção, combo).
- **`Local_AI/estudio_shopee/`** — módulo à parte para gerar fotos de produto com IA
  (remoção de fundo + edição via fal.ai), com um "Modo Gratuito" sem custo de API.

## Como rodar

Pré-requisitos: **Docker Desktop** aberto e **Python 3.10+**.

App principal (Data Warehouse + Cérebro IA), a partir da raiz do submódulo `Local_AI/`:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_local.ps1
```

Detecta sozinho primeira execução (cria `analista_dados_shopee/CHAVES_DADOS.env` a partir
do `.example` e pede para preencher) vs. rotina (sobe o Docker, aplica migrações pendentes,
abre o app). Sobe em **http://localhost:8501**. Detalhes, variáveis de ambiente e páginas:
`Local_AI/analista_dados_shopee/README.md`.

Estúdio de imagens (módulo separado, deps próprias):

```powershell
cd Local_AI/estudio_shopee
streamlit run app.py
```

Segredos do Estúdio (`FAL_KEY`, `OPENAI_API_KEY`, etc.) ficam em `Local_AI/CHAVES.env`
(veja `Local_AI/CHAVES.env.example` para a lista completa com comentários).

## Como testar

- App principal: `Local_AI/analista_dados_shopee/tests/` cobre a camada determinística
  offline (heurísticas, importação de CSV). Não roda contra banco/OpenAI/Shopee reais.
- Estúdio (`gerador_anuncio.py`): **ainda não há suíte automatizada** — é objeto da tarefa
  T-005 (backlog). Hoje a validação é manual (documentada nas tarefas T-001/T-002), sempre
  com a chamada HTTP mockada, sem custo de API real.

## Funcionalidades atuais

### App principal (`analista_dados_shopee`) — já em produção
Sincronização de catálogo/pedidos/saúde da conta/pós-venda via API Shopee v2, importação de
planilhas do Seller Center, cálculo de lucro real por variação, auditoria de IA por
horizonte (7d/30d) com execução de ações aprovadas, e chat text-to-SQL somente-leitura sobre
o Data Warehouse. Descrição completa da arquitetura: `_gestao/ANALISE.md`.

### Estúdio (`estudio_shopee`) — em produção
Upload de foto(s) de peça impressa em 3D, remoção de fundo, composição em canvas, geração de
instrução de edição via LLM local (Groq) e edição da imagem via fal.ai, com refinamento
iterativo e aprovação/salvamento em `fotos_prontas/`.

### Anúncio completo no Estúdio — EM CONSTRUÇÃO (feature desta rodada da fábrica)
Objetivo: gerar título + descrição + palavras-chave do anúncio direto na imagem final
aprovada, usando um modelo de IA com visão (ver `_gestao/ESPECIFICACAO.md`). Estado real
hoje:

- **Pronto (backend):** `Local_AI/estudio_shopee/gerador_anuncio.py` expõe
  `gerar_anuncio_shopee(imagem_bytes, contexto_produto, historico_estilo="") -> dict`
  (chama a API OpenAI REST direto, em JSON mode, com a imagem em data URI; valida o schema
  de retorno `{titulo, descricao, palavras_chave}`). Testado manualmente ponta a ponta com
  rede mockada (T-001, T-002); ainda sem chamada real paga confirmada neste ambiente.
- **Ainda NÃO existe:** nenhum botão/campo na UI do Estúdio chama essa função — não há
  como gerar o anúncio pela tela hoje (T-003, backlog). Também não há persistência do
  anúncio junto do render aprovado (T-004, backlog) nem suíte de testes automatizados
  (T-005, backlog) nem a documentação de uso no `how_to_use.md` do Estúdio (T-006,
  backlog). Acompanhe o progresso em `_gestao/PLANO.md` e `_gestao/tarefas/`.

## Gestão da fábrica

Especificação, plano, decisões e tarefas ficam em `_gestao/` (este projeto foi importado de
uma pasta já existente — `_gestao/ANALISE.md` documenta a arquitetura do sistema herdado, e
`_gestao/ESPECIFICACAO.md`/`PLANO.md` cobrem só a feature nova de anúncio). Protocolo de
tarefas: `../../_sistema/PROTOCOLO_TAREFAS.md`.
