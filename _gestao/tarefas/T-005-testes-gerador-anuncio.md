---
id: T-005
titulo: Testes automatizados do motor de geração de anúncio
projeto: ia-hibrida-limpa
status: concluida
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

### Ciclo 1

- **Critério 1: Arquivo existe** — PASSOU
  - Confirmado: `Local_AI/estudio_shopee/tests/test_gerador_anuncio.py` presente e lido com sucesso.

- **Critério 2: Comando pytest roda sem rede e todos os testes passam** — PASSOU
  - Comando: `python -m pytest Local_AI/estudio_shopee/tests/test_gerador_anuncio.py -v`
  - Resultado: `5 passed in 0.26s`
  - Todas as 5 execuções rodadas passaram sem falhas, sem erros de dependência e sem qualquer tentativa de rede real.

- **Critério 3: Os 5 casos do Contexto estão cobertos** — PASSOU
  1. `test_chave_ausente_nao_tenta_rede` — Validado: chave ausente levanta `ErroGeracaoAnuncio` com "OPENAI_API_KEY" na mensagem, mock de rede configurado para falhar se chamado.
  2. `test_resposta_http_de_erro` — Validado: status 500 levanta `ErroGeracaoAnuncio` com "500" na mensagem.
  3. `test_content_nao_e_json_valido` — Validado: content inválido levanta `ErroGeracaoAnuncio` com "JSON" na mensagem.
  4. `test_json_valido_faltando_chave_esperada` — Validado: JSON faltando `palavras_chave` levanta `ErroGeracaoAnuncio` com "palavras_chave" na mensagem.
  5. `test_caminho_feliz_retorna_anuncio_completo` — Validado: resposta completa retorna dict esperado com as 3 chaves, e a chamada HTTP é rastreada (1 vez, com image_url e text presentes).

- **Critério 4: Nenhum teste depende de OPENAI_API_KEY real** — PASSOU
  - Confirmado: todos os testes usam `monkeypatch.setattr(gerador_anuncio, "OPENAI_API_KEY", ...)` para sobrescrever explicitamente (vazia ou "sk-fake-para-teste").
  - Teste adicional rodado com `$env:OPENAI_API_KEY = ""` (bash/powershell): `test_chave_ausente_nao_tenta_rede` passou sem dependência de valor real.
  - Nenhuma chamada real a `requests.post` feita em nenhum teste — `HTTP_SESSION` é completamente mockado via `monkeypatch.setattr(gerador_anuncio.HTTP_SESSION, "post", ...)`.
  - `pytest` (versão 9.1.1) instalado e disponível globalmente.

**Resumo:** Todos os 4 critérios de aceite PASSARAM. Cobertura completa dos 5 casos, testes offline puro, sem dependência de credencial real ou chamada de rede.

## Revisão

### Ciclo 1

Diff revisado: `git -C Local_AI show 226a325` (único arquivo novo,
`estudio_shopee/tests/test_gerador_anuncio.py`, 165 linhas) e leitura completa de
`Local_AI/estudio_shopee/gerador_anuncio.py` (implementação testada) linha a linha, para
confirmar que cada asserção de teste corresponde ao comportamento real do código (não só
ao que o teste espera). Também confirmado que o commit no repo externo (`4c0a6e6`) só
move o ponteiro do submódulo + este arquivo de tarefa — nenhum outro código tocado.

Pontos verificados especificamente por pedido do despacho:

- **Mock bloqueia rede de verdade, não só simula sucesso:** `HTTP_SESSION` é a MESMA
  instância `requests.Session()` module-level usada dentro de `chamar_openai_visao`
  (linha 63 de `gerador_anuncio.py`); o teste faz
  `monkeypatch.setattr(gerador_anuncio.HTTP_SESSION, "post", ...)`, ou seja, substitui o
  método `.post` na própria instância que o código de produção chama — não há caminho de
  código que ainda bata em rede real. `monkeypatch` desfaz automaticamente ao final de
  cada teste, sem vazamento entre testes.
- **Teste de "chave ausente" prova rede nunca tocada, não só o resultado final:**
  `test_chave_ausente_nao_tenta_rede` usa `_mock_post_nunca_deve_ser_chamado`, que instala
  em `HTTP_SESSION.post` uma função que levanta `AssertionError` se for chamada — isto é,
  se o código de produção tentasse rede antes de checar a credencial, o teste falharia por
  esse `AssertionError` explícito (não passaria "por acaso"). Confirmado lendo
  `chamar_openai_visao` (linha 94): `_validar_credencial()` é a PRIMEIRA linha da função,
  antes de montar `payload`/`headers` e antes do bloco `try` que chama
  `HTTP_SESSION.post` — a ordem real do código garante que o teste está testando o
  cenário certo, não um artefato do mock.
- **Correspondência teste↔código para os outros 4 casos**, confirmada lendo
  `chamar_openai_visao`/`_validar_resposta_anuncio`:
  - Caso 2 (`status_code=500`): `_RespostaFake.raise_for_status` levanta `HTTPError` só
    se `status_code >= 400` (linha 37 do teste), que o código captura na linha 122 e
    reformata com `response.status_code` na mensagem — `match="500"` bate no valor real
    interpolado, não em coincidência.
  - Caso 3 (content não-JSON): fluxo passa por `response.json()` → `mensagem["content"]`
    → `json.loads(conteudo)` (linha 150 do módulo) → `JSONDecodeError` → mensagem com
    "JSON" — confirmado.
  - Caso 4 (falta `palavras_chave`): `_validar_resposta_anuncio` (linha 292) usa
    `resultado.get("palavras_chave")` que retorna `None` quando ausente, cai no branch de
    erro com "palavras_chave" na mensagem — confirmado.
  - Caso 5 (caminho feliz): teste captura a chamada real (`chamadas.append`) e verifica
    `len(chamadas) == 1` + presença de blocos `text`/`image_url` em
    `payload["messages"][1]["content"]`, batendo exatamente com o que
    `_construir_mensagens_anuncio` (linha 253) monta — não é um "mock que sempre passa",
    de fato inspeciona o payload HTTP produzido pelo código real.
- **Isolamento de ambiente:** confirmado que `Local_AI/CHAVES.env` não existe nesta
  máquina (só `.example`) e que, mesmo que existisse, todo teste sobrescreve
  `gerador_anuncio.OPENAI_API_KEY` explicitamente via monkeypatch antes de qualquer
  chamada — não há dependência do valor carregado em `load_dotenv` no import do módulo.
- **Escopo:** nenhum arquivo fora de `estudio_shopee/tests/` foi tocado; não há colisão de
  nome de módulo (`gerador_anuncio.py` só existe em `estudio_shopee/`), nem
  `conftest.py`/`pytest.ini` pré-existentes que pudessem alterar o `sys.path` de forma
  inesperada.

Nota menor (não reprova): `sys.path.insert(0, ...)` no topo do arquivo de teste não é
revertido ao final — inofensivo rodando este arquivo isolado (como o critério de aceite
pede), mas se um dia a suíte completa do projeto rodar num único `pytest` (hoje não
acontece; `analista_dados_shopee` e `estudio_shopee` não compartilham execução), poderia
in princípio interferir na resolução de outro módulo homônimo. Não é o caso hoje.

**Veredito: aprovado sem ressalvas.** Os 5 testes exercitam o código real (não um dublê
que sempre concorda com o teste), os mocks efetivamente impedem qualquer chamada de rede
(inclusive comprovado por asserção que derruba o teste se a rede for tocada no caso de
credencial ausente), e as mensagens/condições de erro verificadas correspondem
exatamente ao que `gerador_anuncio.py` produz.
