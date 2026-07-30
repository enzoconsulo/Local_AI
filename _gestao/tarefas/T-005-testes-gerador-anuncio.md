---
id: T-005
titulo: Testes automatizados do motor de geração de anúncio
projeto: ia-hibrida-limpa
status: em-teste
prioridade: media
dependencias: [T-002]
areas: [Local_AI/estudio_shopee/tests/]
tentativas: 1
agente: ia-integracao
criada: 2026-07-27
atualizada: 2026-07-29
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

### Ciclo 1
- Criado `Local_AI/estudio_shopee/tests/test_gerador_anuncio.py` (pasta `tests/` do
  módulo ainda não existia — criada agora). Testes em `pytest`, offline puro, cobrindo os
  5 casos mínimos pedidos no Contexto, todos exercitando o fluxo completo via
  `gerar_anuncio_shopee` (que por sua vez chama `chamar_openai_visao`):
  1. `test_chave_ausente_nao_tenta_rede` — `OPENAI_API_KEY` monkeypatchada para `""` +
     mock de `HTTP_SESSION.post` que derruba o teste (`AssertionError`) se for chamado;
     confirma `ErroGeracaoAnuncio` com "OPENAI_API_KEY" na mensagem e zero tentativa de
     rede.
  2. `test_resposta_http_de_erro` — resposta fake com `status_code=500`;
     `raise_for_status` simulado levanta `requests.exceptions.HTTPError`; confirma
     `ErroGeracaoAnuncio` com "500" na mensagem.
  3. `test_content_nao_e_json_valido` — envelope OpenAI válido mas `message.content` é uma
     string não-JSON (`"isso não é um JSON{{{"`); confirma `ErroGeracaoAnuncio` com "JSON"
     na mensagem.
  4. `test_json_valido_faltando_chave_esperada` — `content` é JSON válido mas sem
     `palavras_chave`; confirma `ErroGeracaoAnuncio` com "palavras_chave" na mensagem
     (validação de schema em `_validar_resposta_anuncio`).
  5. `test_caminho_feliz_retorna_anuncio_completo` — `content` é o JSON completo esperado;
     confirma que `gerar_anuncio_shopee` retorna exatamente o dict com as 3 chaves e,
     como checagem extra (não é só "mock que sempre passa"), que a chamada HTTP foi feita
     exatamente 1 vez e que a mensagem multimodal enviada de fato contém um bloco
     `image_url` e um bloco `text`.
- Mock de rede: `monkeypatch.setattr(gerador_anuncio.HTTP_SESSION, "post", ...)` — a mesma
  sessão `requests.Session()` reaproveitada pelo módulo (nunca `requests` real). Cada teste
  também monkeypatcha `gerador_anuncio.OPENAI_API_KEY` explicitamente (vazia ou
  `"sk-fake-para-teste"`), então nenhum teste depende do valor real que porventura exista
  em `Local_AI/CHAVES.env` no ambiente local (confirmado: esse arquivo nem existe nesta
  máquina, só o `.example` — mas os testes não dependem disso de qualquer forma).
- Um `_RespostaFake` (stub mínimo com `status_code`/`text`/`json()`/`raise_for_status()`)
  substitui o objeto `Response` do `requests` nos testes — evita qualquer dependência de
  rede real mesmo indiretamente.
- **Decisão registrada aqui (não em DECISOES.md, por não ser decisão de arquitetura do
  projeto):** `pytest` não estava instalado no Python global usado pelo projeto
  (`C:\Users\enzoc\AppData\Local\Programs\Python\Python312\python.exe`) — instalado via
  `pip install pytest` (pacote padrão de teste, exigido literalmente pelo critério de
  aceite `python -m pytest ...`; não é dependência do código do projeto, não entra em
  nenhum `requirements.txt`, só é necessária para rodar a suíte).
- Comando de teste (critério de aceite, rodado ao final, ver resultado abaixo):
  `python -m pytest Local_AI/estudio_shopee/tests/test_gerador_anuncio.py -v`
- Nenhuma chamada de rede real feita em nenhum momento; `OPENAI_API_KEY` real nunca foi
  usada (não existe nem no ambiente).
- Arquivo tocado: `Local_AI/estudio_shopee/tests/test_gerador_anuncio.py` (novo). Nenhum
  outro arquivo alterado — em particular, `Local_AI/estudio_shopee/app.py` (em edição por
  outro agente em paralelo, T-003) não foi tocado.
- Resultado: `5 passed in 1.26s` (todos os 5 testes, sem falhas, sem skip).
- Commit no submódulo `Local_AI` (branch `main`): `git add estudio_shopee/tests/` (só a
  pasta nova, sem tocar `estudio_shopee/app.py`, que segue modificado e não commitado pelo
  outro agente em paralelo) + `git commit -m "T-005: testes offline de
  gerador_anuncio.py (mock HTTP)"`. Hash: `226a325`.
- Commit no repo externo `ia-hibrida-limpa` (ponteiro do submódulo + este arquivo de
  tarefa): hash `4c0a6e6`.
- Status deixado como `em-teste` (não pulei teste: a tarefa toca código executável e o
  critério de aceite pede rodar a suíte explicitamente).

## Verificação


## Revisão
