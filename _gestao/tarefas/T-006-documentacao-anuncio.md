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
atualizada: 2026-07-27
---

## Objetivo
Documentar a função de Anúncio Shopee no `how_to_use.md` do Estúdio e preencher o
`CLAUDE.md` do projeto (hoje só com os placeholders do template) com o contexto técnico real
do sistema, incluindo a função nova.

## Contexto
- `Local_AI/estudio_shopee/how_to_use.md` hoje descreve uma versão BEM antiga do app (v5.0,
  fluxo RunPod puro) — já desatualizada em vários pontos em relação ao `app.py` atual (v15.0).
  NÃO é objetivo desta tarefa reescrever o documento inteiro (isso é um trabalho à parte,
  fora de escopo aqui) — apenas ACRESCENTAR uma seção nova e coerente descrevendo o fluxo do
  Anúncio Shopee (quando a seção aparece, o que é gerado, como editar, onde é salvo ao
  aprovar o catálogo).
- `projetos/ia-hibrida-limpa/CLAUDE.md` ainda tem os placeholders do template
  (`_sistema/templates/CLAUDE-projeto.md`). Preencha com base em `_gestao/ANALISE.md` (que
  tem o mapeamento real da arquitetura) + a função nova desta rodada. Seções a preencher:
  Stack, Como rodar, Como testar, Arquitetura em 1 minuto, Convenções, Armadilhas conhecidas.
  Não invente comandos — use os já documentados em `ANALISE.md` (ex.: `run_local.ps1` para o
  app principal; `streamlit run app.py` de dentro de `Local_AI/estudio_shopee/` para o
  Estúdio) e nos arquivos de teste/critérios das tarefas anteriores (ex.:
  `python -m pytest Local_AI/estudio_shopee/tests/ -v`).
- `Local_AI/estudio_shopee/requirements.txt` não existe hoje — as deps do Estúdio estão só
  em comentário no topo de `app.py`. Criar esse arquivo é OPCIONAL nesta tarefa (só faça se
  for rápido): se criar, inclua as deps já citadas no docstring de `app.py`
  (`streamlit requests python-dotenv pillow rembg fal-client`) — não precisa fixar versões.
- Esta tarefa é majoritariamente de documentação; o orquestrador pode optar por pular a etapa
  `em-teste` do protocolo, já que não há código executável novo aqui.

## Critérios de aceite
- [ ] `Local_AI/estudio_shopee/how_to_use.md` tem uma seção nova descrevendo o fluxo do
      Anúncio Shopee (quando aparece, o que é gerado, como editar, onde é salvo).
- [ ] `projetos/ia-hibrida-limpa/CLAUDE.md` está preenchido (sem os placeholders `<...>` do
      template) refletindo o projeto real, incluindo a função de Anúncio Shopee.
- [ ] Nenhum arquivo de código (`.py`) é alterado nesta tarefa, exceto, no máximo, a criação
      opcional de `Local_AI/estudio_shopee/requirements.txt`.

## Notas de execução


## Verificação


## Revisão
