---
id: T-001
titulo: Cliente OpenAI REST multimodal (plumbing) para o Estúdio
projeto: ia-hibrida-limpa
status: pronta
prioridade: alta
dependencias: []
areas: [Local_AI/estudio_shopee/gerador_anuncio.py, Local_AI/CHAVES.env.example]
tentativas: 0
agente: ia-integracao
criada: 2026-07-27
atualizada: 2026-07-27
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
- [ ] `Local_AI/estudio_shopee/gerador_anuncio.py` existe e não importa `streamlit`.
- [ ] Expõe uma exceção `ErroGeracaoAnuncio(Exception)`.
- [ ] Expõe uma função (ex.: `chamar_openai_visao(mensagens: list[dict], timeout: int = 60) -> dict`)
      que faz POST para a URL de chat completions (`OPENAI_API_BASE_URL`, com fallback para
      `https://api.openai.com/v1`, mesma lógica de montagem de URL do `cerebro/config.py`),
      com `response_format={"type": "json_object"}`, e retorna o JSON já decodificado do
      campo `choices[0].message.content` da resposta.
- [ ] `OPENAI_API_KEY` ausente/vazia levanta `ErroGeracaoAnuncio` com mensagem clara ANTES de
      qualquer chamada de rede (verificável chamando a função sem a env setada).
- [ ] Resposta HTTP com status de erro (>=400) levanta `ErroGeracaoAnuncio` com a causa
      original anexada (não deixa subir `requests.exceptions.HTTPError` cru nem um
      traceback genérico sem contexto).
- [ ] `content` que não é JSON válido (ex.: string solta) levanta `ErroGeracaoAnuncio` com
      mensagem clara, em vez de deixar `json.JSONDecodeError` subir sem tratamento.
- [ ] `Local_AI/CHAVES.env.example` existe e documenta, com comentários curtos: `FAL_KEY`,
      `GROQ`, `RUNPOD_KEY`, `ENDPOINT_ID_RUNPOD_vLLM`, `ENDPOINT_ID_RUNPOD_DADOS`,
      `OPENAI_API_KEY`, `OPENAI_MODEL_ANUNCIO` (com o default sugerido) e
      `OPENAI_API_BASE_URL` (comentário indicando que é opcional).
- [ ] `python -m py_compile Local_AI/estudio_shopee/gerador_anuncio.py` executa sem erro.

## Notas de execução


## Verificação


## Revisão
