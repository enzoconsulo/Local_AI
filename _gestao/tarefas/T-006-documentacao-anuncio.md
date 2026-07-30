---
id: T-006
titulo: Documentação — Anúncio Shopee no how_to_use e no CLAUDE.md do projeto
projeto: ia-hibrida-limpa
status: em-execucao
prioridade: baixa
dependencias: [T-004, T-005]
areas: [Local_AI/estudio_shopee/how_to_use.md, projetos/ia-hibrida-limpa/CLAUDE.md, Local_AI/estudio_shopee/requirements.txt]
tentativas: 2
criada: 2026-07-27
atualizada: 2026-07-30
---

## Objetivo
Documentar a função de Anúncio Shopee no `how_to_use.md` do Estúdio e revisar/atualizar o
`CLAUDE.md` do projeto (já preenchido com o contexto técnico real do sistema — ver nota de
atualização no Contexto) para refletir o estado real após T-003/T-004/T-005, incluindo a
função nova.

## Contexto
- `Local_AI/estudio_shopee/how_to_use.md` hoje descreve uma versão BEM antiga do app (v5.0,
  fluxo RunPod puro) — já desatualizada em vários pontos em relação ao `app.py` atual (v15.0).
  NÃO é objetivo desta tarefa reescrever o documento inteiro (isso é um trabalho à parte,
  fora de escopo aqui) — apenas ACRESCENTAR uma seção nova e coerente descrevendo o fluxo do
  Anúncio Shopee (quando a seção aparece, o que é gerado, como editar, onde é salvo ao
  aprovar o catálogo).
- ATUALIZAÇÃO (revisão avulsa de 2026-07-28, ver `DECISOES.md`): ao contrário do que esta
  tarefa presumia quando foi criada, `projetos/ia-hibrida-limpa/CLAUDE.md` JÁ FOI
  preenchido com o contexto técnico real do projeto (Stack, Como rodar, Como testar,
  Arquitetura em 1 minuto, Convenções, Armadilhas conhecidas) — não é mais um placeholder
  do template. Quando esta tarefa rodar (depois de T-004 e T-005), REVISE o arquivo em vez
  de escrevê-lo do zero: confirme que ele ainda bate com o estado real e atualize
  especificamente (a) a seção "Como testar", que hoje diz "sem suíte automatizada ainda"
  para `estudio_shopee`/`gerador_anuncio.py` — trocar pela referência real à suíte de
  T-005 (`python -m pytest Local_AI/estudio_shopee/tests/ -v`); (b) a nota em "Armadilhas
  conhecidas" sobre "Feature de anúncio incompleta" (hoje diz que não está integrada à
  UI — depois de T-003/T-004 concluídas, corrigir ou remover essa nota); (c) qualquer outro
  trecho que o estado real de T-003/T-004/T-005 tenha tornado desatualizado. Não reescreva
  seções que continuarem corretas. Se por algum motivo o arquivo tiver voltado a ter
  placeholders (ex.: foi resetado), aí sim preencha do zero com base em `_gestao/ANALISE.md`
  como esta tarefa originalmente previa.
- `Local_AI/estudio_shopee/requirements.txt` não existe hoje — as deps do Estúdio estão só
  em comentário no topo de `app.py`. Criar esse arquivo é OPCIONAL nesta tarefa (só faça se
  for rápido): se criar, inclua as deps já citadas no docstring de `app.py`
  (`streamlit requests python-dotenv pillow rembg fal-client`) — não precisa fixar versões.
- Esta tarefa é majoritariamente de documentação; o orquestrador pode optar por pular a etapa
  `em-teste` do protocolo, já que não há código executável novo aqui.

## Critérios de aceite
- [ ] `Local_AI/estudio_shopee/how_to_use.md` tem uma seção nova descrevendo o fluxo do
      Anúncio Shopee (quando aparece, o que é gerado, como editar, onde é salvo).
- [ ] `projetos/ia-hibrida-limpa/CLAUDE.md` reflete o estado real do projeto após
      T-003/T-004/T-005 (sem placeholders `<...>` do template, sem trechos descrevendo
      como "pendente"/"incompleta" algo que já foi entregue), incluindo a função de
      Anúncio Shopee.
- [ ] Nenhum arquivo de código (`.py`) é alterado nesta tarefa, exceto, no máximo, a criação
      opcional de `Local_AI/estudio_shopee/requirements.txt`.

## Notas de execução

(2026-07-28 — planejador, revisão avulsa pedida via painel, sem gatilho de bloqueio/
esgotamento: tarefa ainda em `backlog`/0 tentativas, editada diretamente — ver
`DECISOES.md`. Corrigida a premissa de que `CLAUDE.md` do projeto ainda tinha
placeholders — na verdade já foi preenchido; texto e critério de aceite ajustados para
"revisar/atualizar" em vez de "preencher do zero". Nenhuma mudança de escopo além disso.)

### Ciclo 1

Lidos antes de começar: `_sistema/PROTOCOLO_TAREFAS.md`, `CLAUDE.md` do projeto,
`_gestao/ESPECIFICACAO.md`, `_gestao/DECISOES.md`, e o código real tocado pela feature
(`Local_AI/estudio_shopee/gerador_anuncio.py` inteiro, e os trechos de
`Local_AI/estudio_shopee/app.py` da Etapa 4 "Anúncio Shopee" — handler do botão "📝 Gerar
Anúncio Completo", campos editáveis, e o handler de "✅ Aprovar Catálogo" que salva o
`.txt` junto do `.png`) para documentar o comportamento REAL implementado, não uma versão
prospectiva.

**1. `Local_AI/estudio_shopee/how_to_use.md`** — acrescentada uma seção nova, "Anúncio
Shopee (Etapa 4 — feature nova)", inserida entre a seção "Aprovação" e "Limpeza de
Memória" (o resto do documento, que descreve a v5.0/RunPod bem desatualizada, não foi
tocado — fora de escopo desta tarefa, conforme o Contexto já registrado). A seção nova
cobre: quando a etapa aparece (depois de pelo menos uma renderização, na aba "🎨 Gerador
Automático"), o que é enviado à IA (a mesma imagem final + contexto textual da Etapa 2),
o que é devolvido (título/descrição/palavras-chave em JSON, sempre em PT-BR, modelo
configurável via `OPENAI_MODEL_ANUNCIO`), como editar (campos `Título do anúncio`/
`Descrição do anúncio`, com contador de caracteres no título), onde é salvo (
`fotos_prontas/render_<timestamp>_v<versao>.txt`, mesmo nome-base do `.png`, só ao clicar
em "✅ Aprovar Catálogo" e só se um anúncio foi gerado) e como falhas aparecem (mensagem
`❌ ...` sem derrubar a aba). Inclui nota de que a etapa só existe na aba com custo (Fal.ai)
— o "📋 Modo Gratuito" não tem essa etapa, porque não há bytes de imagem final dentro do
app nesse fluxo.

**2. `projetos/ia-hibrida-limpa/CLAUDE.md`** — revisado (não reescrito do zero, já que não
tinha voltado a ter placeholders — confirmado por leitura). Trechos desatualizados
corrigidos:
- **Stack**: "estudio_shopee ainda não tem suíte automatizada" → agora cita a suíte
  `pytest` existente em `tests/`, com a ressalva de que é só do motor
  (`gerador_anuncio.py`), não da UI.
- **Como testar**: "sem suíte automatizada ainda (T-005, backlog)" → trocado pelo comando
  real `python -m pytest Local_AI/estudio_shopee/tests/ -v` (rodei antes de escrever, ver
  Testes/Validação abaixo — 5 testes, todos verdes), citando os 5 casos cobertos
  (`chamar_openai_visao`/`gerar_anuncio_shopee`: credencial ausente, erro HTTP, JSON
  inválido, schema incompleto, caminho feliz) e deixando claro que `app.py` (a UI em si)
  continua sem suíte automatizada própria.
- **Arquitetura em 1 minuto**: a descrição de `estudio_shopee/gerador_anuncio.py` dizia
  "ainda não chamado por nenhum botão da UI (T-003 pendente)" — corrigido para descrever o
  fluxo real e integrado (botão "📝 Gerar Anúncio Completo" em T-003, persistência em
  `fotos_prontas/*.txt` em T-004, suíte de testes em T-005).
- **Armadilhas conhecidas**: a nota "Feature de anúncio incompleta... não documente/anuncie
  a feature como utilizável de ponta a ponta até T-003/T-004 saírem do backlog" foi
  substituída por uma nota afirmativa ("Anúncio Shopee é feature completa e integrada",
  T-001 a T-005 concluídas — confirmado no frontmatter de cada tarefa antes de escrever
  essa frase) descrevendo o fluxo de ponta a ponta e apontando para a seção nova do
  `how_to_use.md`. A nota de "Cobertura de testes é parcial" foi mantida (é verdade real:
  `app.py` segue sem suíte automatizada), só ajustada para não contradizer a existência da
  suíte do motor.
- Verificado (grep por `pendente|incompleta|<...>|TODO|placeholder`) que não sobrou
  nenhuma referência desatualizada no arquivo.

**3. `Local_AI/estudio_shopee/requirements.txt`** (criado, item opcional do escopo) — uma
dependência por linha, sem versão fixada (mesmo estilo de
`Local_AI/analista_dados_shopee/requirements.txt`, usado como referência), com as deps já
citadas no docstring de `app.py`: `streamlit requests python-dotenv pillow rembg
fal-client`. Comentário deixa explícito que `pytest` (usado só para rodar a suíte de
T-005) não entra aqui — não é dependência do app em si.

**Nenhum arquivo `.py` foi alterado** — confirmado com `git -C Local_AI status
--porcelain` antes de commitar: só `estudio_shopee/how_to_use.md` (modificado) e
`estudio_shopee/requirements.txt` (novo).

**Testes/validação:**
- `python -m pytest Local_AI/estudio_shopee/tests/ -v` (comando citado no CLAUDE.md
  atualizado) rodado de verdade nesta sessão: `5 passed in 0.24s` — confirma que a
  referência nova no CLAUDE.md é exata, não uma suposição.
- Leitura completa de `gerador_anuncio.py` e dos trechos relevantes de `app.py` (handler
  do botão de geração, campos editáveis, handler de "Aprovar Catálogo") para garantir que
  cada afirmação da documentação nova (nome dos botões, nome dos campos, formato/nome do
  arquivo salvo, condição de quando a etapa aparece) corresponde ao código real, não a uma
  versão idealizada.
- Não havia código executável novo para exercitar via servidor/CLI (tarefa é só
  documentação + `requirements.txt`, que não tem lógica para rodar).

**Sugestão para o orquestrador (fora de escopo desta tarefa, não executada):** o resto de
`how_to_use.md` (a parte v5.0/RunPod) segue bem desatualizado em relação ao `app.py` atual
(v15.0, Fal.ai) — já registrado como fora de escopo no Contexto original desta tarefa; uma
reescrita completa do documento poderia virar uma tarefa própria futura, se fizer sentido
para o backlog.

**Commits:**
- Submódulo `Local_AI` (branch `main`): `git add estudio_shopee/how_to_use.md
  estudio_shopee/requirements.txt` + `git commit -m "T-006: documentar Anuncio Shopee no
  how_to_use.md e adicionar requirements.txt"`. Hash: `67a4b3a`.
- Repo externo `ia-hibrida-limpa` (ponteiro do submódulo + `CLAUDE.md` + este arquivo de
  tarefa): `git add CLAUDE.md Local_AI _gestao/tarefas/T-006-documentacao-anuncio.md` +
  `git commit -m "T-006: documentacao do Anuncio Shopee (how_to_use.md + CLAUDE.md do
  projeto)"`. Hash: `915f835`. (`_gestao/PLANO.md` e
  `_gestao/tarefas/T-004-persistencia-anuncio.md` apareciam modificados no `git status` da
  árvore antes desta tarefa começar — não são trabalho meu, deixados de fora do `git add`
  de propósito.)

**Status deixado como `em-execucao`, propositalmente** (instrução explícita do despacho):
tarefa majoritariamente de documentação, sem código executável novo — o orquestrador vai
decidir e registrar a dispensa da etapa `em-teste`, mandando direto para `em-revisao`.

### Ciclo 2

Lidos antes de corrigir: `_sistema/PROTOCOLO_TAREFAS.md`, esta tarefa inteira (Objetivo,
Contexto, Notas de execução Ciclo 1, Verificação, Revisão Ciclo 1), `CLAUDE.md` do projeto.
Retrabalho — corrigido exatamente o achado `[importante]` da Revisão Ciclo 1, mais o
achado `[menor]` (não bloqueante, mas rápido).

**Achado `[importante]` corrigido** — `Local_AI/estudio_shopee/how_to_use.md:297`: a frase
citava entre crases um rótulo de botão fixo (`🚀 Enviar para Renderização`) copiado por
engano da seção antiga v5.0; o botão real que dispara a renderização (`app.py:632`) tem
rótulo DINÂMICO (`f"🚀 Gerar {num_variacoes}x com {nome_motor_valor}
(~${custo_estimado:.3f})"`, ex.: "🚀 Gerar 2x com Nano Banana Pro (~$0.090)"). Reli
`app.py:610-633` para confirmar o formato exato antes de escrever. Frase reescrita para
descrever o botão sem citar um rótulo literal inexistente, citando o formato dinâmico com
um exemplo concreto em vez de um texto fixo.

**Achado `[menor]` corrigido** — `how_to_use.md:342-345`: "aparece... acima da seção" era
impreciso; reli `app.py:807-838` (bloco da seção "4. Anúncio Shopee") e confirmei que o
`st.error` roda dentro do próprio `if st.button(...)` da Etapa 4, ou seja, DENTRO da
seção, logo abaixo do botão de gerar e antes dos campos editáveis — não acima da seção
inteira. Frase corrigida para refletir a posição real.

Nenhum outro trecho tocado. Confirmado com `git -C Local_AI status --porcelain`: só
`estudio_shopee/how_to_use.md` modificado, nenhum `.py`.

**Commits:**
- Submódulo `Local_AI` (branch `main`): `git add estudio_shopee/how_to_use.md` + `git
  commit -m "T-006: corrigir citacao de rotulo de botao inexistente no how_to_use.md
  (Ciclo 2)"`. Hash: `4c91f38`.
- Repo externo `ia-hibrida-limpa` (ponteiro do submódulo + arquivo da tarefa): `git add
  Local_AI _gestao/tarefas/T-006-documentacao-anuncio.md` + `git commit -m "T-006: Ciclo 2
  - corrigir achados da revisao no how_to_use.md"`. Hash: `7ff5a0a`. (`_gestao/PLANO.md` e
  `_gestao/tarefas/T-004-persistencia-anuncio.md` seguem modificados na árvore por outro
  agente — não são trabalho meu, deixados de fora do `git add`, como no Ciclo 1.)

**Status deixado como `em-execucao`, propositalmente** (instrução explícita do despacho):
o orquestrador vai mandar direto para `em-revisao`, pulando `em-teste` de novo (tarefa
continua sem código executável tocado).

## Verificação

**Etapa `em-teste` dispensada pelo orquestrador (2026-07-30):** tarefa majoritariamente de
documentação; critério de aceite 3 confirma que nenhum `.py` foi alterado (conferido via
`git -C Local_AI show --stat 67a4b3a`: só `how_to_use.md` e `requirements.txt`, ambos sem
lógica executável). Nada aqui exige execução de software para validar — segue direto para
revisão, conforme a regra do CLAUDE.md ("tarefas triviais... podem pular em-teste... só
quando a tarefa não toca código executável").

## Revisão

### Ciclo 1

Lidos antes de revisar: `_sistema/PROTOCOLO_TAREFAS.md`, esta tarefa (Objetivo, Contexto,
Notas de execução), `CLAUDE.md` do projeto. Diff revisado por completo nos dois commits:
submódulo `Local_AI` (`git -C Local_AI show 67a4b3a`, branch `main` — `how_to_use.md` +
`requirements.txt` novo) e repo externo `ia-hibrida-limpa` (`git show 915f835` — `CLAUDE.md`
+ ponteiro do submódulo + arquivo da tarefa). Para cada afirmação factual da documentação
nova (nomes de botão, nomes de campo, condição de quando a seção aparece, formato/nome do
arquivo salvo, comportamento de erro, contagem/descrição dos testes, deps do
`requirements.txt`), fui conferir contra o código real: `gerador_anuncio.py` inteiro,
`app.py` linhas ~245-345 (helpers `salvar_anuncio_txt`/`resetar_anuncio`) e ~690-862 (Etapa
3 "Mesa de Refinamento" + Etapa 4 "Anúncio Shopee" completa, incluindo a aba "📋 Modo
Gratuito" para validar a nota de que ela não tem a etapa), `tests/test_gerador_anuncio.py`
inteiro, e `_gestao/tarefas/T-001` a `T-005` (frontmatter, para confirmar o status
`concluida` citado no CLAUDE.md).

A esmagadora maioria das afirmações bate exatamente com o código: botão "📝 Gerar Anúncio
Completo" (`app.py:814`), botão "✅ Aprovar Catálogo" (`app.py:769`), campos "Título do
anúncio"/"Descrição do anúncio" com contador de caracteres só no título (`app.py:841-844`,
`847-852`), condição de salvamento do `.txt` só se `anuncio_atual` existir e só ao aprovar
(`app.py:777-801`, conteúdo exato "Título:/Descrição:/Palavras-chave:" confirmado em
`salvar_anuncio_txt`, `app.py:249-265`), nome-base idêntico ao `.png`
(`render_<timestamp>_v<versao>`), modelo padrão `gpt-5.6-luna` e env var
`OPENAI_MODEL_ANUNCIO` (`gerador_anuncio.py:61`, confirmado também em
`CHAVES.env.example:22`), a suíte de 5 testes descrita caso a caso (bate 1:1 com
`test_gerador_anuncio.py`), a nota de que o "📋 Modo Gratuito" não tem a etapa (confirmado:
esse fluxo só baixa o canvas e gera prompt de texto, nunca tem bytes de imagem final dentro
do app), o `requirements.txt` (deps idênticas ao docstring de `app.py:38-39`, mesmo estilo
de `analista_dados_shopee/requirements.txt`), e as atualizações do `CLAUDE.md` (Stack, Como
testar, Arquitetura, Armadilhas) — todas as menções a "pendente"/"incompleta"/placeholder
foram de fato removidas (confirmei com grep), e o status "T-001 a T-005 concluídas" citado
bate com o frontmatter real de cada tarefa.

**[importante] `Local_AI/estudio_shopee/how_to_use.md:297`** — a seção nova, na frase
"depois de pelo menos uma renderização via `🚀 Enviar para Renderização`", cita entre
crases (convenção usada no resto da MESMA seção nova para rótulos literais de botão — ex.:
`📝 Gerar Anúncio Completo`, `✅ Aprovar Catálogo`, ambos corretos) um nome de botão que NÃO
existe no `app.py` atual. O botão real que dispara a renderização (`app.py:632`) é
`st.button(f"🚀 Gerar {num_variacoes}x com {nome_motor_valor} (~${custo_estimado:.3f})", ...)`
— um rótulo dinâmico como "🚀 Gerar 2x com Nano Banana Pro (~$0.090)", nunca o texto fixo
"Enviar para Renderização". Esse texto foi copiado da seção antiga "Etapa 3 — Geração" do
mesmo `how_to_use.md` (linha 198), que já documenta a v5.0 desatualizada (fora do escopo
desta tarefa, reconhecidamente) — mas ao reaproveitar a frase dentro da seção NOVA (que
esta tarefa escreveu para descrever o app ATUAL), o erro passou a valer também para a
documentação nova, que deveria refletir o código real conforme o próprio Contexto da
tarefa exige. Cenário concreto: usuário lê a seção "Anúncio Shopee" para entender quando
ela aparece, procura na UI um botão com o texto literal "🚀 Enviar para Renderização" para
confirmar que está no passo certo, e não encontra — o botão real tem um rótulo totalmente
diferente (nome do motor + custo estimado). Correção é trivial (trocar a citação por algo
não literal, ex. "depois de clicar no botão 🚀 de geração/renderização", ou citar o texto
fixo comum aos dois estados dinâmicos).

**[menor]** `how_to_use.md:342-345` — "aparece como uma mensagem de erro (`❌ ...`) acima
da seção" é impreciso: no código (`app.py:823-837`) o `st.error` roda DENTRO da seção "4.
Anúncio Shopee" (depois do botão, antes dos campos editáveis), não acima da seção inteira.
Não muda o comportamento relevante para o usuário (a mensagem aparece, a aba não quebra) —
não reprova a tarefa.

Fora esses dois pontos, aprovado: nenhuma outra afirmação de botão/campo/comportamento
divirgiu do código real; nenhum `.py` foi tocado (confirmado via `git -C Local_AI show
--stat 67a4b3a`); critérios de aceite 2 e 3 verificados diretamente.

**Veredito: REPROVADA** — achado `[importante]` único, correção de uma linha em
`how_to_use.md`.
