---
id: T-001
titulo: Cliente OpenAI REST multimodal (plumbing) para o Estúdio
projeto: ia-hibrida-limpa
status: em-teste
prioridade: alta
dependencias: []
areas: [Local_AI/estudio_shopee/gerador_anuncio.py, Local_AI/CHAVES.env.example]
tentativas: 2
agente: ia-integracao
criada: 2026-07-27
atualizada: 2026-07-28
---

## Objetivo
Criar `Local_AI/estudio_shopee/gerador_anuncio.py` com a infraestrutura de chamada HTTP
direta (sem SDK) à API OpenAI Chat Completions em modo JSON, aceitando mensagens
multimodais (texto + imagem), e com carregamento de configuração/erros tratados — a base
sobre a qual T-002 vai construir a geração do anúncio propriamente dita.

## Contexto
- Leia `_gestao/ESPECIFICACAO.md` (seção "Feature nova") e `_gestao/DECISOES.md` (decisão
  "Anúncio do Estúdio usa OpenAI REST direto...") antes de começar.
- Padrão de referência no próprio projeto: `Local_AI/analista_dados_shopee/cerebro/config.py`
  (carregamento de env com `python-dotenv`, `requests.Session()` reaproveitada,
  `OPENAI_API_BASE_URL` opcional com fallback para `https://api.openai.com/v1`) e
  `cerebro/motor_ia.py` (chamada em JSON mode, parsing defensivo). NÃO importe nada de
  `analista_dados_shopee/` — é outro módulo, com deps e segredos próprios; apenas inspire-se
  no padrão, sem acoplar os dois.
- O Estúdio hoje carrega variáveis de `Local_AI/CHAVES.env` (veja `app.py`, topo:
  `load_dotenv(dotenv_path=ROOT_DIR / "CHAVES.env")`, onde `ROOT_DIR = Path(__file__).resolve().parent.parent`
  aponta para `Local_AI/`). Este módulo novo deve carregar as MESMAS variáveis desse mesmo
  arquivo (`OPENAI_API_KEY`, `OPENAI_MODEL_ANUNCIO`, `OPENAI_API_BASE_URL`), de forma
  independente (não dependa de `app.py` já ter rodado `load_dotenv` — o módulo deve
  funcionar mesmo importado isoladamente, ex. em um teste).
- Este arquivo `Local_AI/CHAVES.env` (segredos reais) não existe nesta árvore de trabalho
  (está fora do controle de versão, coberto por `.gitignore`) — não crie você mesmo o
  arquivo real com segredos; crie apenas o `.example`.
- NÃO existe hoje um `Local_AI/CHAVES.env.example`. Ao criá-lo, inclua também as variáveis
  que `Local_AI/llm.py` já exige (`GROQ`, `RUNPOD_KEY`, `ENDPOINT_ID_RUNPOD_vLLM`,
  `ENDPOINT_ID_RUNPOD_DADOS`) e o `FAL_KEY` que `app.py` já exige — hoje nenhuma delas tem
  um `.example` documentado; aproveite para deixar isso completo.
- Este módulo NÃO deve importar `streamlit` — precisa ser testável isoladamente (T-005 vai
  escrever testes com a chamada de rede mockada).
- Modelo default sugerido para `OPENAI_MODEL_ANUNCIO`: `gpt-5.6-luna` (mesma família de
  baixo custo/reasoning já usada no app principal para tarefas rápidas) — mas mantenha
  configurável via env, sem hardcode fora do default.

## Critérios de aceite
- [x] `Local_AI/estudio_shopee/gerador_anuncio.py` existe e não importa `streamlit`.
- [x] Expõe uma exceção `ErroGeracaoAnuncio(Exception)`.
- [x] Expõe uma função (ex.: `chamar_openai_visao(mensagens: list[dict], timeout: int = 60) -> dict`)
      que faz POST para a URL de chat completions (`OPENAI_API_BASE_URL`, com fallback para
      `https://api.openai.com/v1`, mesma lógica de montagem de URL do `cerebro/config.py`),
      com `response_format={"type": "json_object"}`, e retorna o JSON já decodificado do
      campo `choices[0].message.content` da resposta.
- [x] `OPENAI_API_KEY` ausente/vazia levanta `ErroGeracaoAnuncio` com mensagem clara ANTES de
      qualquer chamada de rede (verificável chamando a função sem a env setada).
- [x] Resposta HTTP com status de erro (>=400) levanta `ErroGeracaoAnuncio` com a causa
      original anexada (não deixa subir `requests.exceptions.HTTPError` cru nem um
      traceback genérico sem contexto).
- [x] `content` que não é JSON válido (ex.: string solta) levanta `ErroGeracaoAnuncio` com
      mensagem clara, em vez de deixar `json.JSONDecodeError` subir sem tratamento.
- [x] `Local_AI/CHAVES.env.example` existe e documenta, com comentários curtos: `FAL_KEY`,
      `GROQ`, `RUNPOD_KEY`, `ENDPOINT_ID_RUNPOD_vLLM`, `ENDPOINT_ID_RUNPOD_DADOS`,
      `OPENAI_API_KEY`, `OPENAI_MODEL_ANUNCIO` (com o default sugerido) e
      `OPENAI_API_BASE_URL` (comentário indicando que é opcional).
- [x] `python -m py_compile Local_AI/estudio_shopee/gerador_anuncio.py` executa sem erro.

## Notas de execução

### Ciclo 1 (2026-07-28)
Implementação da infraestrutura de chamada HTTP direta (sem SDK) à API OpenAI Chat
Completions em JSON mode, seguindo o padrão de `cerebro/config.py`/`cerebro/motor_ia.py`
(sessão `requests` reaproveitada, JSON mode, parsing defensivo, exceção própria).

Arquivos criados:
- `Local_AI/estudio_shopee/gerador_anuncio.py` — módulo novo, sem import de `streamlit`.
  Carrega `OPENAI_API_KEY`, `OPENAI_MODEL_ANUNCIO` (default `gpt-5.6-luna`) e
  `OPENAI_API_BASE_URL` (fallback `https://api.openai.com/v1`, mesma lógica de montagem de
  URL de `cerebro/config.py`) via `load_dotenv(ROOT_DIR / "CHAVES.env")` própria — não
  depende de `app.py` já ter rodado `load_dotenv`. Expõe `ErroGeracaoAnuncio(Exception)` e
  `chamar_openai_visao(mensagens: list[dict], timeout: int = 60) -> dict`, que faz POST em
  `response_format={"type": "json_object"}` e devolve `choices[0].message.content` já
  decodificado. Validação de credencial ocorre ANTES do POST (levanta
  `ErroGeracaoAnuncio` sem tocar a rede); erro HTTP (`response.raise_for_status()`) é
  capturado e relançado como `ErroGeracaoAnuncio` com `raise ... from e` (causa original
  anexada); timeout de rede e `RequestException` genérica também viram
  `ErroGeracaoAnuncio`; `content` que não é JSON válido levanta `ErroGeracaoAnuncio` a
  partir do `json.JSONDecodeError` capturado (nunca sobe cru). Este arquivo é só o
  plumbing (T-001); a construção do prompt/mensagens específicas do anúncio fica para
  T-002.
- `Local_AI/CHAVES.env.example` — não existia; documenta com comentários curtos todas as
  variáveis já exigidas por `llm.py` (`GROQ`, `RUNPOD_KEY`, `ENDPOINT_ID_RUNPOD_vLLM`,
  `ENDPOINT_ID_RUNPOD_DADOS`) e por `app.py` (`FAL_KEY`), além das novas
  (`OPENAI_API_KEY`, `OPENAI_MODEL_ANUNCIO=gpt-5.6-luna`, `OPENAI_API_BASE_URL` opcional).
  Confirmado que `*.env` está no `.gitignore` de `Local_AI/` mas `*.env.example` não casa
  com esse padrão (termina em `.example`, não `.env`) — o arquivo fica versionado
  normalmente. Não foi criado nenhum `CHAVES.env` real (segredos) nesta árvore.

Validação:
- `python -m py_compile Local_AI/estudio_shopee/gerador_anuncio.py` — sem erro.
- Smoke test manual (fora da suíte formal, só para validar antes de marcar `em-teste`):
  importei o módulo isoladamente e simulei via monkeypatch de `HTTP_SESSION.post`/
  `OPENAI_API_KEY` os 4 cenários dos critérios de aceite — (1) credencial ausente levanta
  `ErroGeracaoAnuncio` sem chamar `.post`; (2) resposta HTTP 401 levanta
  `ErroGeracaoAnuncio` com `__cause__` igual ao `HTTPError` original; (3) `content` não-JSON
  levanta `ErroGeracaoAnuncio` a partir do `JSONDecodeError`; (4) caminho feliz decodifica
  `content` JSON corretamente. `'streamlit' in sys.modules` confirmado `False` após o
  import. Testes automatizados formais (mock de rede, sem custo de API) são objeto de T-005
  — aqui só validei manualmente o plumbing desta tarefa.

Armadilha encontrada: `Local_AI/` é um git submodule dentro do repo do projeto
`ia-hibrida-limpa` (gitlink, `git ls-files -s Local_AI` → modo `160000`, remoto próprio
`git@github.com:enzoconsulo/Local_AI.git`, branch `main`). O código novo desta tarefa foi
commitado no repositório interno de `Local_AI` (branch `main`); o repositório externo do
projeto (`ia-hibrida-limpa`, branch `master`) recebeu, num commit próprio, o ponteiro do
submódulo atualizado + este arquivo de tarefa. Nenhum push foi feito a nenhum remoto
(mantido só local, como o resto da fábrica).

Commits:
- Dentro de `Local_AI/` (submódulo, branch `main`): `T-001: cliente OpenAI REST multimodal
  (gerador_anuncio.py) + CHAVES.env.example`
- No repositório do projeto `ia-hibrida-limpa` (branch `master`): `T-001: cliente OpenAI
  REST multimodal (plumbing) para o Estúdio` (inclui o ponteiro atualizado do submódulo
  `Local_AI` e este arquivo de tarefa)

Status: todos os critérios de aceite verificados manualmente → `em-teste` (T-005 cobre os
testes automatizados formais).

### Ciclo 2 (2026-07-28)

Retrabalho a partir do achado "importante" registrado na seção Revisão (Ciclo 1): em
`chamar_openai_visao`, o bloco final só capturava `json.JSONDecodeError` ao redor de
`json.loads(conteudo)`. Como `conteudo` vem de `message.content`, que a API OpenAI pode
retornar `null` quando o modelo recusa a resposta por moderação/segurança (com o motivo
em `message.refusal` em vez de `content`), `json.loads(None)` levantava `TypeError` cru,
não `ErroGeracaoAnuncio` — quebrando a promessa do próprio docstring da função.

Correção aplicada em `Local_AI/estudio_shopee/gerador_anuncio.py` (bloco final de
`chamar_openai_visao`, antes ~linhas 123-134):
- Passei a guardar a referência a `mensagem` (`corpo_resposta["choices"][0]["message"]`)
  junto da extração de `conteudo`, para poder consultar `refusal` sem nova navegação no
  JSON.
- Adicionei um checagem explícita `if conteudo is None:` ANTES de `json.loads`: se
  `mensagem.get("refusal")` estiver preenchido, levanta `ErroGeracaoAnuncio` expondo o
  motivo da recusa (`"A IA recusou gerar o anúncio: {recusa}"`) — atende a sugestão do
  revisor de expor essa informação, útil para depuração; caso `refusal` também esteja
  vazio, levanta `ErroGeracaoAnuncio` com mensagem genérica de conteúdo nulo.
- No `try/except` de `json.loads(conteudo)`, incluí `TypeError` junto de
  `json.JSONDecodeError` — rede de segurança extra para qualquer outro valor não-string
  que a API venha a devolver em `content` (ex.: número, bool), não só `None` (que já é
  pego pela checagem explícita acima).
- Nota menor 1 do revisor (retorno não-dict não validado) também corrigida: depois do
  `json.loads`, adicionei `if not isinstance(resultado, dict): raise ErroGeracaoAnuncio(...)`
  — assim a assinatura `-> dict` da função passa a ser garantida em tempo de execução, não
  só na anotação de tipo.
- Nota menor 2 do revisor (lembrete sobre a palavra "json" precisar aparecer nas
  mensagens ao usar `response_format=json_object`) é sobre o conteúdo das mensagens, que
  só é montado em T-002 — não há nada a mudar neste módulo de plumbing (T-001); registrado
  aqui só para constar que foi lido e avaliado, sem ação necessária nesta tarefa.

Validação:
- `python -m py_compile Local_AI/estudio_shopee/gerador_anuncio.py` (a partir da raiz do
  submódulo `Local_AI/`) — sem erro.
- Script de verificação temporário (`Local_AI/estudio_shopee/_teste_temp_t001_ciclo2.py`,
  executado com `python -m estudio_shopee._teste_temp_t001_ciclo2` a partir de `Local_AI/`,
  sem nenhuma chamada de rede real — `HTTP_SESSION.post` monkeypatchado) cobrindo 5
  cenários: (1) `content=None` sem `refusal` → `ErroGeracaoAnuncio` com mensagem genérica;
  (2) `content=None` com `refusal="conteudo sensivel detectado"` → `ErroGeracaoAnuncio`
  expõe o motivo da recusa na mensagem; (3) `content` é JSON válido mas não é objeto
  (`"[1, 2, 3]"`) → `ErroGeracaoAnuncio` (nota menor 1); (4) regressão — `content`
  não-JSON (string solta) continua levantando `ErroGeracaoAnuncio` a partir do
  `JSONDecodeError`; (5) regressão — caminho feliz (`content` = objeto JSON) continua
  decodificando o `dict` corretamente. **Os 5 cenários passaram.** Script apagado após a
  validação — não sobrou na árvore de trabalho (confirmado com `git status --short` limpo
  em `Local_AI/`, só `estudio_shopee/gerador_anuncio.py` modificado).

Commits:
- Dentro de `Local_AI/` (submódulo, branch `main`): `75515c0` — "T-001: corrige TypeError
  cru em content nulo (json.loads) — expoe recusa da API e valida tipo dict do retorno".
- No repositório do projeto `ia-hibrida-limpa` (branch `master`): ponteiro do submódulo
  atualizado + este arquivo de tarefa (hash registrado após o commit, abaixo do
  `git log` local).

Status: achado do revisor (Ciclo 1) corrigido e validado; ambas as notas menores também
endereçadas → `em-teste`.

## Verificação

### Ciclo 1 (2026-07-28) — testador

Executado com Python 3.12.5 (`requests` 2.34.2, `python-dotenv` 1.2.2 instalados). Todas
as verificações abaixo rodaram o código de verdade (import real do módulo, HTTP mockado
via monkeypatch de `HTTP_SESSION.post`, sem nenhuma chamada de rede real) a partir de
`Local_AI/estudio_shopee/`; nenhum arquivo `CHAVES.env` real foi criado.

- [x] PASSOU — `gerador_anuncio.py` existe e não importa `streamlit`. Evidência: bloqueei
  `streamlit` via `sys.meta_path` antes do `import estudio_shopee.gerador_anuncio` e
  confirmei `"streamlit" not in sys.modules` depois do import; `grep -i streamlit` no
  arquivo só encontra 2 menções em comentário/docstring (linhas 14-15, 44), nenhum
  `import`.
- [x] PASSOU — Expõe `ErroGeracaoAnuncio(Exception)` (linha 31) e
  `chamar_openai_visao(mensagens: list[dict], timeout: int = 60) -> dict` (linha 75) que
  faz POST para `OPENAI_CHAT_COMPLETIONS_URL` com `response_format={"type": "json_object"}`
  e devolve `choices[0].message.content` decodificado. Evidência: monkeypatch de
  `HTTP_SESSION.post` capturando os argumentos da chamada real — `url` terminou em
  `/chat/completions`, `json["response_format"] == {"type": "json_object"}`,
  `timeout == 42` (passado explicitamente), header `Authorization: Bearer chave-fake-teste`
  presente. Lógica de montagem de URL (`OPENAI_API_BASE_URL` com fallback
  `https://api.openai.com/v1`) conferida linha a linha contra
  `analista_dados_shopee/cerebro/config.py` (linhas 63-68 lá vs. 50-55 aqui) — idêntica.
- [x] PASSOU — `OPENAI_API_KEY` ausente/vazia levanta `ErroGeracaoAnuncio` ANTES de
  qualquer chamada de rede. Evidência: com `ga.OPENAI_API_KEY = ""` e `HTTP_SESSION.post`
  substituído por uma função que levanta `AssertionError` se for chamada, a chamada a
  `chamar_openai_visao(...)` levantou `ErroGeracaoAnuncio: "OPENAI_API_KEY não configurada.
  Adicione a chave em Local_AI/CHAVES.env (veja Local_AI/CHAVES.env.example) e reinicie o
  Estúdio."` sem nunca invocar `.post` (flag de controle permaneceu `False`).
- [x] PASSOU — Resposta HTTP >=400 levanta `ErroGeracaoAnuncio` com a causa original
  anexada. Evidência: mock de resposta HTTP 401 (`raise_for_status` levanta
  `requests.exceptions.HTTPError`) → capturado `ErroGeracaoAnuncio: "API OpenAI retornou
  erro 401: {"error": "unauthorized"}"`, com `e.__cause__` sendo exatamente a instância de
  `requests.exceptions.HTTPError` original (`isinstance` confirmado).
- [x] PASSOU — `content` que não é JSON válido levanta `ErroGeracaoAnuncio` em vez de
  deixar `json.JSONDecodeError` subir cru. Evidência: mock de resposta HTTP 200 com
  `content = "isto nao eh json { solto"` → capturado `ErroGeracaoAnuncio: "A IA não
  devolveu um JSON válido: Expecting value: line 1 column 1 (char 0)"`.
- [x] PASSOU (extra, caminho de sucesso mencionado no despacho) — mock de resposta HTTP
  200 com `content` sendo um JSON válido (`{"titulo": "Produto X", ...}`) →
  `chamar_openai_visao` devolveu o `dict` já decodificado corretamente
  (`resultado["titulo"] == "Produto X"`).
- [x] PASSOU — `Local_AI/CHAVES.env.example` existe (`Local_AI/CHAVES.env.example`, 25
  linhas) e documenta com comentários curtos as 7 variáveis pedidas: `FAL_KEY`, `GROQ`,
  `RUNPOD_KEY`, `ENDPOINT_ID_RUNPOD_vLLM`, `ENDPOINT_ID_RUNPOD_DADOS`, `OPENAI_API_KEY`,
  `OPENAI_MODEL_ANUNCIO=gpt-5.6-luna` (default sugerido presente) e `OPENAI_API_BASE_URL`
  (comentário "Opcional: deixe vazio para usar https://api.openai.com/v1"). Confirmado
  `ls Local_AI/CHAVES.env` → arquivo real não existe nesta árvore (segredo não vazou); o
  `.example` está fora do padrão `*.env` do `.gitignore` (termina em `.example`), então
  fica versionado normalmente — coerente com o commit registrado.
- [x] PASSOU — `python -m py_compile Local_AI/estudio_shopee/gerador_anuncio.py` executado
  a partir da raiz do submódulo `Local_AI/` → saída limpa, sem erro (exit code 0).

Notas adicionais (não geram reprovação):
- Suíte completa do projeto: não há suíte de testes automatizados para
  `estudio_shopee/` ainda (T-005 é quem vai criá-la). Existe uma suíte em
  `Local_AI/analista_dados_shopee/tests/` (módulo totalmente independente, não tocado por
  esta tarefa — confirmado por `DECISOES.md` e pelo `areas` do frontmatter desta tarefa);
  tentei rodá-la (`python -m pytest tests/`) e o ambiente global não tem `pytest`
  instalado (`No module named pytest`) — esse módulo tem `requirements.txt` próprio,
  presumivelmente com venv dedicado não ativado nesta sessão. Como T-001 não tocou nenhum
  arquivo desse módulo, não é motivo de reprovação; registro aqui só para o orquestrador
  ter visibilidade caso queira validar aquele módulo separadamente.
- Estrutura de submódulo git (`Local_AI` como gitlink) verificada: `git log` dentro de
  `Local_AI/` mostra o commit `ac883d7 T-001: cliente OpenAI REST multimodal
  (gerador_anuncio.py) + CHAVES.env.example` no topo (branch `main`); `git log` no
  repositório externo mostra `ab7eee0 T-001: cliente OpenAI REST multimodal (plumbing)
  para o Estudio` no topo (branch `master`), com o ponteiro do submódulo atualizado.
  `git status --short` em ambos os níveis está limpo (nenhum resquício do script de
  verificação temporário, removido ao final).

Script de verificação temporário usado (`Local_AI/estudio_shopee/_teste_temp_t001.py`,
com monkeypatch de `HTTP_SESSION.post` para os 4 cenários + captura de payload) foi
apagado após a validação — não sobrou na árvore de trabalho.

**Resultado: 8/8 critérios PASSARAM.**

## Revisão

### Ciclo 1 (2026-07-28) — revisor

Diff revisado: `git -C Local_AI show ac883d7` (commit dentro do submódulo `Local_AI`,
branch `main`) — os dois arquivos tocados (`estudio_shopee/gerador_anuncio.py`,
`CHAVES.env.example`), linha a linha, comparados também contra o padrão de referência
`analista_dados_shopee/cerebro/config.py`.

- [importante] `Local_AI/estudio_shopee/gerador_anuncio.py:131-134` — o último bloco de
  `chamar_openai_visao` só captura `json.JSONDecodeError` ao redor de
  `json.loads(conteudo)`:
  ```python
  try:
      return json.loads(conteudo)
  except json.JSONDecodeError as e:
      raise ErroGeracaoAnuncio(f"A IA não devolveu um JSON válido: {e}") from e
  ```
  Se `conteudo` (extraído em `corpo_resposta["choices"][0]["message"]["content"]`, linha
  125) for `None` — ou qualquer valor não-string —, `json.loads` levanta `TypeError`, não
  `JSONDecodeError`, e essa exceção sobe crua, sem virar `ErroGeracaoAnuncio`. Confirmado
  isoladamente: `json.loads(None)` → `TypeError: the JSON object must be str, bytes or
  bytearray, not NoneType` (testado com `py -c "..."` nesta revisão).
  Cenário concreto de falha: a API OpenAI Chat Completions retorna `message.content =
  null` quando o modelo recusa a resposta por política de segurança/moderação (campo
  `message.refusal` preenchido em vez de `content`) — comportamento documentado da API,
  plausível justamente aqui porque o módulo lida com imagens de produto (visão), que é o
  tipo de conteúdo mais sujeito a recusa por moderação. Nesse caso, em vez de
  `ErroGeracaoAnuncio` com mensagem clara (a promessa do próprio docstring da função:
  "Nunca deixa subir uma exceção crua de requests ou json") e da UI tratando o erro com
  RF-07 ("falha não derruba a aba do Estúdio"), sobe um `TypeError` cru até o chamador —
  o mesmo problema que o critério de aceite de `content` não-JSON pretendia evitar, só
  que para o caso `None`/não-string em vez de string malformada. Correção sugerida (não
  aplicada por mim): incluir `TypeError` no `except` desse bloco, ou validar
  `isinstance(conteudo, str)` antes de chamar `json.loads`.

Notas menores (não reprovam a tarefa):
- `chamar_openai_visao` está anotada como `-> dict`, mas nada impede que
  `json.loads(conteudo)` devolva um tipo diferente (lista, número, string) se o modelo
  devolver um JSON válido que não seja um objeto — T-002, ao consumir o retorno, deve
  tratar esse caso ou reforçar no prompt que a saída precisa ser um objeto JSON.
- `response_format={"type": "json_object"}` (linha 95) exige, pela própria API OpenAI,
  que a palavra "json" apareça em alguma mensagem `system`/`user`, senão a API responde
  HTTP 400 (já coberto pelo tratamento de erro genérico desta tarefa, então não é bug de
  T-001) — só um lembrete para quem monta as mensagens em T-002.

Verificado e sem problema: validação de credencial antes de qualquer chamada de rede;
`raise ... from e` preservando a causa original em todos os `except`; montagem de URL
idêntica ao padrão de `cerebro/config.py`; nenhum segredo real commitado (`CHAVES.env`
não existe na árvore, só o `.example` com placeholders); `.gitignore` de `Local_AI`
(`*.env`) não gera falso-negativo para `CHAVES.env.example` (confirmado com
`git check-ignore -v`); variáveis documentadas no `.example` batem exatamente (nome e
grafia) com o que `llm.py` (`GROQ`, `RUNPOD_KEY`, `ENDPOINT_ID_RUNPOD_vLLM`,
`ENDPOINT_ID_RUNPOD_DADOS`) e `app.py` (`FAL_KEY`) já exigem; módulo não importa
`streamlit`.

**Resultado: 1 achado importante → devolvida para execução.**
