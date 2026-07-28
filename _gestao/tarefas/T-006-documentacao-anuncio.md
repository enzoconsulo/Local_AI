---
id: T-006
titulo: Documentação — Anúncio Shopee no how_to_use e no CLAUDE.md do projeto
projeto: ia-hibrida-limpa
status: backlog
prioridade: baixa
dependencias: [T-004, T-005]
areas: [Local_AI/estudio_shopee/how_to_use.md, projetos/ia-hibrida-limpa/CLAUDE.md, Local_AI/estudio_shopee/requirements.txt]
tentativas: 0
criada: 2026-07-27
atualizada: 2026-07-28
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

## Verificação


## Revisão
