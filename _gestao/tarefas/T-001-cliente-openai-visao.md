---
id: T-001
titulo: Cliente OpenAI REST multimodal (plumbing) para o Estúdio
projeto: ia-hibrida-limpa
status: em-teste
prioridade: alta
dependencias: []
areas: [Local_AI/estudio_shopee/gerador_anuncio.py, Local_AI/CHAVES.env.example]
tentativas: 1
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

## Verificação


## Revisão
