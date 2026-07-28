---
id: T-002
titulo: Prompt de copywriting e schema do anúncio Shopee
projeto: ia-hibrida-limpa
status: em-teste
prioridade: alta
dependencias: [T-001]
areas: [Local_AI/estudio_shopee/gerador_anuncio.py]
tentativas: 1
agente: ia-integracao
criada: 2026-07-27
atualizada: 2026-07-28
---

## Objetivo
Implementar, em cima do cliente montado em T-001, a função que de fato gera o anúncio
completo (título + descrição + palavras-chave) a partir da imagem final do produto e do
contexto textual, com um prompt de sistema elaborado para copywriting de vendas na Shopee, e
validação da resposta.

## Contexto
- Leia `_gestao/ESPECIFICACAO.md` (RF-02 a RF-05) antes de escrever o prompt.
- A imagem final já é manipulada em `app.py` como bytes/base64 (veja `construir_data_uri` em
  `Local_AI/estudio_shopee/app.py`, que gera `data:{mime};base64,{...}`). Para o payload do
  OpenAI Chat Completions, o formato de mensagem com imagem é uma `content` em lista, ex.:
  `{"role": "user", "content": [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": data_uri}}]}`.
  Não duplique a lógica de montar o data URI: mova `construir_data_uri` para
  `gerador_anuncio.py` (ou um novo módulo utilitário compartilhado dentro de
  `estudio_shopee/`) e importe-a de volta em `app.py` — decida o local mais simples, mas
  evite ter a MESMA função copiada em dois arquivos.
- Pesquisa feita pelo planejador (ver `_gestao/ESPECIFICACAO.md`, seção Riscos): a Shopee
  aceita título até ~256 caracteres e descrição até ~5.000, mas o prompt deve pedir texto BEM
  abaixo disso (título por volta de 120–150 caracteres, descrição objetiva estruturada em
  blocos) e evitar excesso de emojis/símbolos especiais no título por segurança.
- O prompt de sistema deve deixar claro para o modelo: (1) basear título/descrição SOMENTE no
  que é visualmente observável na imagem (produto, cor/material aparente, cenário/ângulo/
  estilo) e no contexto textual fornecido (nome do produto, material declarado, estilo
  escolhido) — nunca inventar especificações técnicas não visíveis nem informadas; (2)
  título com termos de busca prováveis + gatilho de venda, sem virar clickbait enganoso; (3)
  descrição estruturada: abertura chamativa, bullets de benefícios/diferenciais,
  especificações visíveis, chamada para ação; (4) responder em português (BR) — diferente do
  prompt de EDIÇÃO de imagem do resto do arquivo (`DIRETRIZES_SISTEMA`), que é em inglês para
  o motor fal.ai; este é para o comprador brasileiro.
- `contexto_produto` deve aceitar pelo menos: nome/descrição curta do produto, cor/material,
  estilo (Catálogo/Lifestyle/Ambiente) — os mesmos dados já reunidos em
  `st.session_state.dados_atual` em `app.py` (não precisa reusar a struct exata, só os
  mesmos campos de conteúdo).

## Critérios de aceite
- [x] `gerar_anuncio_shopee(imagem_bytes: bytes, contexto_produto: dict, historico_estilo: str = "") -> dict`
      existe em `gerador_anuncio.py` e usa `chamar_openai_visao` (de T-001) internamente.
- [x] O retorno é um dict com exatamente as chaves `titulo` (str), `descricao` (str) e
      `palavras_chave` (list[str]).
- [x] O prompt de sistema usado instrui explicitamente a IA a se basear no que é visualmente
      observável na imagem enviada + no contexto textual, sem inventar especificações não
      visíveis nem informadas (trecho do prompt legível no código, não é preciso testar a
      qualidade semântica de forma automatizada).
- [x] Resposta da IA com algum campo faltando, com tipo errado, ou com `palavras_chave` que
      não é uma lista, levanta `ErroGeracaoAnuncio` com mensagem clara — a função nunca
      retorna um dict incompleto/malformado silenciosamente.
- [x] `construir_data_uri` (ou equivalente) não está duplicada entre `app.py` e
      `gerador_anuncio.py` — existe em um único lugar e é importada onde for necessária.
- [x] `python -m py_compile Local_AI/estudio_shopee/gerador_anuncio.py` executa sem erro.
- [x] Nas Notas de execução, documente como a função foi exercitada: chamada real (se havia
      `OPENAI_API_KEY` disponível no ambiente do executor) OU, na ausência de chave, um teste
      manual local da etapa de VALIDAÇÃO/parsing com uma resposta simulada (sem rede), para
      provar que o schema e os erros funcionam como esperado.

## Notas de execução

### Ciclo 1 (2026-07-28)

Implementada, em cima do plumbing de T-001, a geração propriamente dita do anúncio da
Shopee: prompt de sistema de copywriting, montagem da mensagem multimodal (texto +
imagem) e validação defensiva do schema de resposta.

Arquivos alterados:
- `Local_AI/estudio_shopee/gerador_anuncio.py` — adicionado (sem alterar o que já existia
  de T-001):
  - `construir_data_uri(imagem_bytes, mime_type="image/jpeg") -> str` — MOVIDA de `app.py`
    para cá (mesma implementação exata: `base64.b64encode(...).decode("utf-8")` na data
    URI `data:{mime};base64,{...}`). Passou a ser o único lugar onde a função existe;
    `import base64` adicionado ao topo do módulo.
  - `PROMPT_SISTEMA_ANUNCIO` — prompt de sistema em português (BR), instruindo
    explicitamente: (1) basear título/descrição SOMENTE no que é visualmente observável na
    imagem (produto, cor/material aparente, formato, cenário/fundo/ângulo, estilo de
    composição) + no contexto textual do vendedor, com uma regra em destaque ("REGRA MAIS
    IMPORTANTE — NUNCA INVENTE") proibindo specs técnicas não visíveis nem informadas
    (dimensões, peso, resistência, compatibilidade, garantia, marca, certificações); (2)
    título com termos de busca prováveis + gatilho de venda real (nunca clickbait
    enganoso), alvo de 120–150 caracteres (limite técnico Shopee ~256), no máximo 1 emoji;
    (3) descrição estruturada em 4 blocos (abertura, bullets de benefícios/diferenciais,
    especificações visíveis, chamada para ação), objetiva e bem abaixo do limite de ~5.000
    caracteres; (4) palavras-chave curtas (1–4 palavras); (5) responder 100% em português
    (BR) — diferente de `DIRETRIZES_SISTEMA` (em inglês, para o motor de edição de imagem
    fal.ai, que este prompt não toca). A palavra "JSON" aparece várias vezes no prompt de
    sistema (exigência da API OpenAI para `response_format=json_object`, apontada pelo
    revisor da T-001).
  - `_montar_texto_contexto_produto(contexto_produto, historico_estilo) -> str` — monta o
    bloco de texto do usuário a partir de `contexto_produto` (chaves aceitas, todas
    opcionais: `produto`/`nome`, `produtos_formatados`, `cor`/`material`, `estilo`,
    `instrucao`/`cenario` — mesmos campos de conteúdo já reunidos em
    `st.session_state.dados_atual` no `app.py`, sem depender da struct exata). Se nenhuma
    chave estiver preenchida, insere aviso explícito para a IA se basear só na imagem.
    `historico_estilo` (opcional; anúncios já aprovados) entra como bloco à parte, com
    aviso explícito de que é referência de TOM/ESTRUTURA apenas — nunca de conteúdo (mesmo
    padrão da "blindagem" já usada em `app.py` para a memória de prompts de imagem).
  - `_construir_mensagens_anuncio(imagem_bytes, contexto_produto, historico_estilo) ->
    list[dict]` — monta as `mensagens` no formato exigido pela API: `system` com
    `PROMPT_SISTEMA_ANUNCIO` e `user` com `content` em lista
    (`{"type": "text", ...}` + `{"type": "image_url", "image_url": {"url": data_uri}}`),
    usando `construir_data_uri` internamente.
  - `_validar_resposta_anuncio(resultado: dict) -> dict` — valida e normaliza a resposta já
    decodificada por `chamar_openai_visao`: `titulo` precisa ser `str` não vazia (após
    strip), `descricao` idem, `palavras_chave` precisa ser `list` não vazia com todos os
    itens `str` não vazios; qualquer desvio levanta `ErroGeracaoAnuncio` com mensagem
    específica dizendo qual campo falhou e o tipo recebido (nunca deixa passar um dict
    incompleto). Retorna um dict novo só com as 3 chaves esperadas, já com `.strip()`
    aplicado.
  - `gerar_anuncio_shopee(imagem_bytes, contexto_produto, historico_estilo="") -> dict` —
    função pública pedida pelo critério de aceite: valida `imagem_bytes` não vazia (erro
    ANTES de qualquer chamada, mesmo padrão de `_validar_credencial` em T-001), monta as
    mensagens, chama `chamar_openai_visao(mensagens)` (T-001) e devolve o resultado já
    passado por `_validar_resposta_anuncio`.
- `Local_AI/estudio_shopee/app.py` — removida a definição local de `construir_data_uri`
  (linhas antigas ~261-263, dentro da seção "INTEGRAÇÃO NATIVA FAL.AI") e adicionado
  `from gerador_anuncio import construir_data_uri` logo após o bloco de import do
  `fal_client` (import direto, mesmo padrão do resto do arquivo: quando o Streamlit roda
  `streamlit run app.py` a partir de dentro de `estudio_shopee/`, o diretório do próprio
  script entra no `sys.path`, então `import gerador_anuncio` funciona sem precisar do
  prefixo de pacote `estudio_shopee.`). Os dois pontos de uso existentes
  (`data_uri = construir_data_uri(imagem_final_pre_api)` e
  `data_uri_ref = construir_data_uri(st.session_state.img_recortada_bytes)`) continuam
  funcionando sem alteração, agora chamando a função importada. `import base64` continua
  em `app.py` porque ainda é usado em outros pontos (`base64.b64decode`/`b64encode` das
  variações geradas) — não removido.
  Confirmado escopo: T-003 (Fase 2 do PLANO.md) é quem cuida da integração do botão/UI
  ("Gerar Anúncio Completo", campos editáveis) — esta tarefa (Fase 1) ficou só no backend,
  sem adicionar nenhum botão/campo novo em `app.py`, só o import compartilhado.

Validação (sem `OPENAI_API_KEY` no ambiente do executor — confirmado
`echo "${OPENAI_API_KEY:+yes}"` vazio e `Local_AI/CHAVES.env` inexistente nesta árvore, só
o `.example` de T-001; nenhuma chamada de rede real foi feita):
- `python -m py_compile Local_AI/estudio_shopee/gerador_anuncio.py` e
  `python -m py_compile Local_AI/estudio_shopee/app.py` (a partir da raiz do submódulo
  `Local_AI/`) — ambos sem erro.
- Confirmado `'streamlit' not in sys.modules` após `import estudio_shopee.gerador_anuncio`
  com `streamlit` bloqueado via `sys.meta_path` — módulo continua sem importar
  `streamlit`.
- Script de verificação temporário
  (`Local_AI/estudio_shopee/_teste_temp_t002.py`, rodado com
  `python -m estudio_shopee._teste_temp_t002` a partir de `Local_AI/`, com
  `HTTP_SESSION.post` monkeypatchado — nenhuma chamada de rede real) cobrindo 11 cenários,
  **todos passaram**:
  1. Caminho feliz: resposta simulada com schema completo e correto → `gerar_anuncio_shopee`
     devolve exatamente `{"titulo": ..., "descricao": ..., "palavras_chave": [...]}`.
  2. `titulo` ausente → `ErroGeracaoAnuncio`.
  3. `titulo` com tipo errado (`int`) → `ErroGeracaoAnuncio`.
  4. `descricao` ausente → `ErroGeracaoAnuncio`.
  5. `palavras_chave` é `str` em vez de `list` → `ErroGeracaoAnuncio`.
  6. `palavras_chave` é lista vazia → `ErroGeracaoAnuncio`.
  7. `palavras_chave` com item não-string (`int`) → `ErroGeracaoAnuncio`.
  8. `titulo` é string só com espaços (`"   "`) → `ErroGeracaoAnuncio` (falha o `.strip()`).
  9. `content` da API é uma lista JSON válida (não objeto) → `ErroGeracaoAnuncio` (herdado
     da validação de T-001 em `chamar_openai_visao`, confirma que a composição das duas
     camadas de validação não deixa nada passar cru).
  10. `imagem_bytes=b""` → `ErroGeracaoAnuncio` levantada ANTES de `HTTP_SESSION.post` ser
      chamado (flag de chamada de rede permaneceu `False`).
  11. Verificação do payload multimodal construído: `messages[0]` (`system`) contém
      "NUNCA INVENTE", "JSON" e "português"; `messages[1]` (`user`) tem `content` em lista
      com um bloco `text` (contendo o nome do produto e a cor informados em
      `contexto_produto`, e o texto de `historico_estilo` com o aviso "NUNCA copie") e um
      bloco `image_url` cujo `url` começa com `data:image/jpeg;base64,` (confirma o uso de
      `construir_data_uri`); `response_format == {"type": "json_object"}` confirmado no
      payload enviado a `HTTP_SESSION.post`.
  Script apagado ao final da validação — não sobrou na árvore de trabalho (`git status
  --short` em `Local_AI/` confirmado limpo antes do commit, só os 2 arquivos alterados).

Como não havia `OPENAI_API_KEY` disponível neste ambiente, não foi feita nenhuma chamada
real (paga) à API OpenAI — testes automatizados formais com mock de rede completo e
cobertura de regressão são objeto de T-005 (Fase 3); aqui a validação manual acima cobre
tanto a camada de VALIDAÇÃO/parsing quanto a montagem do payload multimodal, incluindo o
uso de `construir_data_uri`.

Commits:
- Dentro de `Local_AI/` (submódulo, branch `main`): `9d0d08c` — "T-002: prompt de
  copywriting e schema do anuncio Shopee" (`gerador_anuncio.py`: prompt +
  `gerar_anuncio_shopee` + `construir_data_uri` movida; `app.py`: import da função
  compartilhada).
- No repositório do projeto `ia-hibrida-limpa` (branch `master`): ponteiro do submódulo
  atualizado + este arquivo de tarefa (hash registrado após o commit, abaixo do `git log`
  local).

Status: critérios de aceite verificados manualmente (sem rede real, sem `OPENAI_API_KEY`
disponível) → `em-teste`.

## Verificação


## Revisão
