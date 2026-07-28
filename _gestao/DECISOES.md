# Decisões — ia-hibrida-limpa

Registro apenas-adição (nunca apagar; decisão revertida ganha nova entrada dizendo isso).
Formato de cada entrada:

## AAAA-MM-DD — <título da decisão>
**Decisão:** <o que foi decidido>
**Motivo:** <por quê; qual alternativa foi descartada e por quê>
**Quem:** <planejador | executor (T-NNN) | orquestrador | usuário>

## 2026-07-27 — Criar ESPECIFICACAO.md e PLANO.md do zero, com escopo focado na feature nova
**Decisão:** Como o projeto foi importado de uma pasta já existente (sem passar por
`/novo-projeto`), não havia `ESPECIFICACAO.md`/`PLANO.md`. Em vez de reescrever a
especificação de todo o sistema já construído, a `ESPECIFICACAO.md` traz uma visão geral
enxuta do sistema (baseada em `_gestao/ANALISE.md`) e detalha com requisitos completos apenas
a função nova pedida (anúncio completo no Estúdio). O `PLANO.md` e as tarefas cobrem só essa
função.
**Motivo:** O sistema já existente (`analista_dados_shopee`) está construído e rodando; gerar
uma especificação retroativa completa dele não agrega valor de planejamento e arriscaria
divergir da implementação real. Focar a especificação/plano na feature nova mantém os
documentos de gestão úteis para orientar as tarefas que a fábrica vai de fato executar.
**Quem:** planejador

## 2026-07-27 — Anúncio do Estúdio usa OpenAI REST direto (visão) em vez de LLM local via Groq
**Decisão:** A geração do anúncio (título + descrição + palavras-chave) usa um cliente OpenAI
REST direto via `requests` (sem SDK), no mesmo padrão já usado pelo app principal em
`cerebro/config.py`/`motor_ia.py` (JSON mode, parsing defensivo), com uma mensagem
multimodal (imagem em data URI + texto). Modelo configurável via `OPENAI_MODEL_ANUNCIO`
(env), com um padrão sensato da mesma família já usada no projeto para tarefas
rápidas/baratas (ex.: `gpt-5.6-luna`, reasoning low).
**Motivo:** O Estúdio já usa um LLM (`chat-rapido`, via LiteLLM local → `groq/llama-3.3-70b-
versatile`) para escrever a instrução de EDIÇÃO da imagem, mas esse modelo só recebe texto —
nunca "vê" a foto. Como o requisito desta feature é o oposto (o texto do anúncio precisa
nascer olhando para a imagem final), é obrigatório um modelo com entrada de imagem.
Alternativa descartada: usar um modelo de visão hospedado na Groq, mantendo tudo dentro do
LiteLLM local já configurado — descartada por não haver precedente validado no projeto para
modelos de visão via Groq/LiteLLM, e por essa oferta mudar com frequência; reusar o padrão
OpenAI REST direto (já provado em produção no app principal) é a opção mais simples e menos
arriscada, sem introduzir um terceiro provedor/SDK.
**Quem:** planejador

## 2026-07-27 — Segredos do anúncio ficam em `Local_AI/CHAVES.env`, não em `CHAVES_DADOS.env`
**Decisão:** As novas variáveis (`OPENAI_API_KEY`, `OPENAI_MODEL_ANUNCIO`,
`OPENAI_API_BASE_URL`) vão no `Local_AI/CHAVES.env` já usado pelo Estúdio (mesmo arquivo do
`FAL_KEY`), e não no `analista_dados_shopee/CHAVES_DADOS.env` do app principal — mesmo que a
chave OpenAI copiada seja, na prática, da mesma conta nos dois arquivos.
**Motivo:** Preservar a independência dos dois módulos (`estudio_shopee` roda separado, com
deps próprias, conforme já registrado em `ANALISE.md`); fazer o Estúdio importar segredos do
app principal criaria acoplamento novo entre dois módulos que hoje não têm nenhuma dependência
um do outro.
**Quem:** planejador

## 2026-07-27 — Fora de escopo nesta rodada: anúncio a partir do fluxo "Modo Gratuito"
**Decisão:** A geração de anúncio só é oferecida na aba "🎨 Gerador Automático" (onde existe
uma imagem final em bytes dentro do app). O fluxo "📋 Modo Gratuito" (usuário gera a imagem
final fora do app, em outra ferramenta) fica fora de escopo por ora.
**Motivo:** No "Modo Gratuito" o app nunca recebe de volta a imagem final gerada — ela é
produzida em outra ferramenta pelo usuário — então não há, hoje, um bytes de imagem final
disponível para servir de entrada visual ao gerador de anúncio sem adicionar um passo de
upload extra. Cortar esse caso simplifica a primeira versão; pode virar uma tarefa futura
(ex.: permitir upload manual da imagem final aprovada também nesse modo).
**Quem:** planejador

## 2026-07-28 — Revisão avulsa do plano restante (T-003 a T-006), pedida via painel sem recorte
**Decisão:** Revisão de saúde geral do que resta do plano, disparada pelo usuário via botão
"replanejar" do painel com o campo de recorte vazio (sem apontar um problema específico) —
NÃO é o replanejamento automático por esgotamento de tentativas (não havia nenhum gatilho
usual: nenhuma tarefa `bloqueada`, nenhuma esgotou tentativas, nenhuma meta de fase deixou de
fazer sentido). Conclusão: **o plano segue válido — nenhuma tarefa foi cancelada, nenhuma
substituta foi criada.** Dois ajustes de texto foram feitos em tarefas ainda em `backlog`
(0 tentativas, não executadas), editadas diretamente por já não fazerem mais sentido como
estavam ou por deixarem de fora avisos relevantes — sem precisar de cancelamento/recriação:

1. **T-003** (`_gestao/tarefas/T-003-ui-anuncio-shopee.md`) — reforçada com as 2 notas
   menores da Revisão de T-002 (Ciclo 1): (a) construir `contexto_produto`/`historico_estilo`
   sempre como valores seguros (`dict`/`str`, nunca `None`) ao ler de
   `st.session_state.dados_atual`, e capturar não só `ErroGeracaoAnuncio` mas também
   `Exception` genérica como rede de segurança no handler do botão (novo critério de aceite
   adicionado para isso); (b) confirmado e registrado que o mime type fixo
   (`image/jpeg`) em `construir_data_uri` NÃO é um problema para este fluxo — a imagem final
   (`imagem_gerada_b64`) vem sempre de `chamar_motor_imagem` (fal.ai), chamado com
   `payload["output_format"] = "jpeg"` (`Local_AI/estudio_shopee/app.py`, linha ~331) —
   confirmado lendo o código; nenhuma mudança de código necessária por essa nota.
2. **T-006** (`_gestao/tarefas/T-006-documentacao-anuncio.md`) — corrigida premissa
   desatualizada: a tarefa presumia que `projetos/ia-hibrida-limpa/CLAUDE.md` ainda tinha os
   placeholders do template, mas o arquivo JÁ FOI preenchido com o contexto técnico real do
   projeto (confirmado por leitura direta nesta revisão) — provavelmente atualizado à parte
   entre ciclos, fora do pipeline desta tarefa especificamente. Texto e critério de aceite
   ajustados de "preencher do zero" para "revisar/atualizar" (seção "Como testar" e a nota de
   "Feature de anúncio incompleta" em "Armadilhas conhecidas" vão ficar desatualizadas depois
   de T-003/T-004/T-005, e é isso que T-006 deve corrigir).

Também confirmados, SEM mudança:
- A decisão de deixar o fluxo "Modo Gratuito" fora de escopo (entrada de 2026-07-27, acima)
  continua válida: nada em T-001/T-002 alterou essa premissa (o "Modo Gratuito" segue sem
  gerar bytes de imagem final dentro do app).
- A decomposição e as dependências de T-003→T-004→(T-005 em paralelo, dependendo só de
  T-002)→T-006 seguem fazendo sentido dado o que foi de fato implementado em
  `gerador_anuncio.py` (assinatura de `gerar_anuncio_shopee`, `construir_data_uri` já movida
  para lá conforme o plano original previa) — nenhuma suposição do plano foi invalidada pela
  implementação real.
- A linha `Marco: pendente` da Fase 1 no `PLANO.md` não foi tocada por esta revisão — é
  pendência de processo separada (falta rodar o marco), não matéria de replanejamento; fica a
  cargo do orquestrador.
**Quem:** planejador

## 2026-07-28 — Redesenho de `_gestao/equipe.json` a partir do estado real do projeto
**Decisão:** Mantida a equipe com os mesmos 2 especialistas já existentes, com os mesmos
`id`s (`ia-integracao`, `streamlit-ui`) — nenhum entrou, nenhum saiu, nenhuma tarefa teve o
campo `agente:` alterado. Os `prompt`s dos dois foram reescritos/afiados para refletir o
estado JÁ IMPLEMENTADO do código (confirmado por leitura direta de `gerador_anuncio.py` e de
`app.py`), em vez de descrever a feature de forma prospectiva:
- `ia-integracao`: escopo confirmado como `Local_AI/estudio_shopee/gerador_anuncio.py` +
  `tests/`; prompt agora cita nominalmente `chamar_openai_visao`/`gerar_anuncio_shopee`/
  `construir_data_uri`/`PROMPT_SISTEMA_ANUNCIO` já existentes (T-001/T-002 concluídas), e
  reforça a regra "nunca inventar especificação não visível/não informada" e o cuidado de
  nunca gastar `OPENAI_API_KEY` real em teste.
- `streamlit-ui`: escopo confirmado como `Local_AI/estudio_shopee/app.py`; prompt agora cita
  nominalmente os estados que precisam ser resetados juntos ao trocar imagem
  (`imagem_gerada_b64`, `candidatos_atual`, `anuncio_atual`), confirmado lendo o arquivo.
**Motivo:** Aplicando as 3 regras de qualidade de equipe (recorte de DOMÍNIO, não de etapa;
menos e mais afiados; não inventar perfil para preencher lista) ao que o projeto É hoje: o
plano ativo (`ESPECIFICACAO.md`/`PLANO.md`) cobre só a feature de Anúncio Shopee no Estúdio,
que se divide em exatamente 2 domínios reais de conhecimento — integração HTTP/IA
(backend, sem Streamlit) e a UI Streamlit do Estúdio (session_state, fluxo de abas) — cada
um já coberto por um especialista existente e referenciado pelas tarefas em backlog (T-001,
T-002, T-005 → `ia-integracao`; T-003, T-004 → `streamlit-ui`). O sistema mais amplo já
existente (`analista_dados_shopee`: Data Warehouse, Cérebro IA, Shopee API, workers) está
fora do escopo desta rodada de planejamento (nenhuma tarefa ativa o toca) — criar um
especialista para ele agora seria inventar perfil para preencher lista, violando a regra 3;
se uma rodada futura de planejamento abrir tarefas ali, um especialista novo (ex.:
`shopee-dw`/`cerebro-ia`) pode ser criado então, com conhecimento de domínio genuíno sobre
`QUERY_DOSSIE`, migrações e `shopee_core`. T-006 (documentação) segue sem `agente:` —
recai no `documentador`/executor genérico, papel fixo da fábrica, coerente com a regra de
que testador/revisor/documentador não entram na equipe.
**Quem:** planejador
