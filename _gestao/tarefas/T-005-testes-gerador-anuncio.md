---
id: T-005
titulo: Testes automatizados do motor de geração de anúncio
projeto: ia-hibrida-limpa
status: pronta
prioridade: media
dependencias: [T-002]
areas: [Local_AI/estudio_shopee/tests/]
tentativas: 0
agente: ia-integracao
criada: 2026-07-27
atualizada: 2026-07-28
---

## Objetivo
Cobrir `gerador_anuncio.py` (T-001 + T-002) com testes automatizados que não dependem de uma
chamada real e paga à API OpenAI — a chamada HTTP é mockada.

## Contexto
- Referência de estilo no próprio projeto: `Local_AI/analista_dados_shopee/tests/` (ex.
  `test_cerebro_correlacoes.py`, `test_importacao_csv.py`) — testes offline puros, sem tocar
  rede/banco real. Não é preciso seguir a estrutura exata desses arquivos, só o espírito
  (offline, determinístico, rápido).
- Ainda não existe pasta `tests/` dentro de `estudio_shopee/` — crie
  `Local_AI/estudio_shopee/tests/test_gerador_anuncio.py`.
- Use `unittest.mock`/`monkeypatch` (pytest) para simular a chamada HTTP (o método usado
  internamente por `chamar_openai_visao`, ex. `requests.Session.post` ou equivalente) — sem
  chamada de rede real em nenhum teste.
- Casos mínimos a cobrir:
  1. `OPENAI_API_KEY` ausente → `ErroGeracaoAnuncio`, sem tentar rede (pode checar que o mock
     de rede nunca foi chamado).
  2. Resposta HTTP com status de erro → `ErroGeracaoAnuncio`.
  3. `content` da resposta não é JSON válido → `ErroGeracaoAnuncio`.
  4. JSON válido mas faltando uma das chaves esperadas (`titulo`/`descricao`/
     `palavras_chave`) → `ErroGeracaoAnuncio`.
  5. Caminho feliz: resposta mockada com JSON completo e válido → `gerar_anuncio_shopee`
     retorna o dict esperado com as 3 chaves.

## Critérios de aceite
- [ ] `Local_AI/estudio_shopee/tests/test_gerador_anuncio.py` existe.
- [ ] `python -m pytest Local_AI/estudio_shopee/tests/test_gerador_anuncio.py -v` roda sem
      tocar rede real e TODOS os testes passam.
- [ ] Os 5 casos do Contexto acima estão cobertos (um teste por caso, no mínimo).
- [ ] Nenhum teste depende de `OPENAI_API_KEY` real estar setada no ambiente (os testes que
      simulam chave ausente devem garantir isso explicitamente, ex. via monkeypatch do env).

## Notas de execução


## Verificação


## Revisão
