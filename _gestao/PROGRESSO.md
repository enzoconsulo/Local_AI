# Progresso — ia-hibrida-limpa

Diário do projeto, entradas mais recentes NO TOPO. Formato:

## AAAA-MM-DD
<o que avançou, estado atual, próximos passos visíveis — 3–6 linhas>

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

## 2026-07-27
Projeto importado pelo painel-fabrica a partir de uma pasta existente. Análise de código enfileirada automaticamente para mapear a arquitetura.
