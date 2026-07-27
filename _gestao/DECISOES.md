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
