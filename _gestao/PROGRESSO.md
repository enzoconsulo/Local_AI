# Progresso — ia-hibrida-limpa

Diário do projeto, entradas mais recentes NO TOPO. Formato:

## AAAA-MM-DD
<o que avançou, estado atual, próximos passos visíveis — 3–6 linhas>

## 2026-07-30
**Escopo desta rodada FECHADO: T-001 a T-006 todas `concluida` e as três fases do
`PLANO.md` com `Marco: aprovado`** (Fase 1 em 28/07; Fases 2 e 3 em 30/07). Entraram nesta
data T-003 (UI "Anúncio Shopee" na aba Gerador Automático), T-004 (persistência do anúncio
junto do render aprovado) e T-006 (documentação) — as três passaram por um ciclo corretivo
em que a REVISÃO achou bug real que o teste tinha deixado passar: troca de variação sem
`resetar_anuncio()`, leitura de `session_state` desatualizado ao salvar, e um rótulo de
botão inexistente citado no `how_to_use.md`. Estado atual: a feature de anúncio é
utilizável ponta a ponta no Estúdio, com suíte offline (5/5, HTTP mockado) e documentação
conferida contra o código. Nenhuma tarefa `pronta` ou `backlog` — sem trabalho pendente.

**Pendência que sobrou, fora do pipeline:** o submódulo `Local_AI` tem **26 commits não
enviados** (`main` ahead 26 de `origin/main`, remoto `git@github.com:enzoconsulo/Local_AI.git`).
O ponteiro do repo externo está correto e bate com o HEAD `4c91f38`, mas esse commit só
existe nesta máquina — quem clonar `ia-hibrida-limpa` e rodar `git submodule update` FALHA,
e é dentro do `Local_AI` que vive todo o código das T-003..T-006. Correção é um
`git -C Local_AI push origin main`; por ser rede/irreversível, aguarda decisão do usuário.

**Registrado e NÃO executado** (fora do escopo desta rodada, candidato a tarefa futura se o
usuário priorizar): o restante do `how_to_use.md` — o fluxo antigo v5.0/RunPod — segue
desatualizado; só a seção "Anúncio Shopee" foi reescrita.

## 2026-07-28
Fase 1 do plano (motor de geração do anúncio) concluída: T-001 (cliente OpenAI REST
multimodal, `Local_AI/estudio_shopee/gerador_anuncio.py`) e T-002 (prompt de copywriting +
`gerar_anuncio_shopee` com validação de schema) passaram por execução, teste e revisão
(ambas aprovadas sem ressalvas bloqueantes) e estão `concluida`. Backend testado
manualmente ponta a ponta com rede mockada — sem chamada real paga confirmada ainda. Estado
atual: a feature de anúncio NÃO é utilizável pela UI — nenhum botão do Estúdio chama
`gerar_anuncio_shopee` hoje. Documentação (README.md do projeto — criado nesta rodada, não
existia — e CLAUDE.md do projeto, preenchido pela primeira vez) atualizada para refletir
esse estado real. Próximos passos: T-003 (botão + campos editáveis na aba "Gerador
Automático"), T-004 (salvar anúncio junto do render aprovado), T-005 (suíte automatizada
com mock de rede) e T-006 (documentar no `how_to_use.md` do Estúdio) seguem em `backlog`,
na ordem do `_gestao/PLANO.md`.

**Fechamento (conferência do estado gravado acima, sem trabalho novo):** `git log`/`git
status` confirmam que nada mudou desde o commit `2ad2465` (árvore limpa, `HEAD` já ali) —
T-001 e T-002 seguem `concluida`, T-003 a T-006 seguem `backlog`, sem retrabalho pendente.
Achado na conferência: **T-002 era a última tarefa da Fase 1, e o protocolo manda
despachar o testador em "modo marco" para verificar a meta da fase ponta a ponta assim que
a última tarefa dela conclui — isso ainda NÃO foi feito.** `_gestao/PLANO.md` continua com
`Marco: pendente` na Fase 1. Ou seja: "Fase 1 concluída" acima descreve as duas tarefas
concluídas, não uma verificação formal de marco já rodada — não confundir as duas coisas.
Próximo passo real (antes de promover T-003 para `pronta`): orquestrador despacha o
testador em modo marco cobrindo a meta da Fase 1 ("motor de geração de anúncio funciona
ponta a ponta — recebe imagem + contexto do produto e devolve `{titulo, descricao,
palavras_chave}` em JSON validado, com erro claro em qualquer falha"); registrar o
resultado na linha `Marco:` da Fase 1 no `PLANO.md`. Só depois promover T-003.

## 2026-07-27
Projeto importado pelo painel-fabrica a partir de uma pasta existente. Análise de código enfileirada automaticamente para mapear a arquitetura.
