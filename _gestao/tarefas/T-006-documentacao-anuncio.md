---
id: T-006
titulo: Documentação — Anúncio Shopee no how_to_use e no CLAUDE.md do projeto
projeto: ia-hibrida-limpa
status: em-execucao
prioridade: baixa
dependencias: [T-004, T-005]
areas: [Local_AI/estudio_shopee/how_to_use.md, projetos/ia-hibrida-limpa/CLAUDE.md, Local_AI/estudio_shopee/requirements.txt]
tentativas: 1
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

## Verificação


## Revisão
