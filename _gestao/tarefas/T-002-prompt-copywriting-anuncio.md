---
id: T-002
titulo: Prompt de copywriting e schema do anúncio Shopee
projeto: ia-hibrida-limpa
status: backlog
prioridade: alta
dependencias: [T-001]
areas: [Local_AI/estudio_shopee/gerador_anuncio.py]
tentativas: 0
agente: ia-integracao
criada: 2026-07-27
atualizada: 2026-07-27
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
- [ ] `gerar_anuncio_shopee(imagem_bytes: bytes, contexto_produto: dict, historico_estilo: str = "") -> dict`
      existe em `gerador_anuncio.py` e usa `chamar_openai_visao` (de T-001) internamente.
- [ ] O retorno é um dict com exatamente as chaves `titulo` (str), `descricao` (str) e
      `palavras_chave` (list[str]).
- [ ] O prompt de sistema usado instrui explicitamente a IA a se basear no que é visualmente
      observável na imagem enviada + no contexto textual, sem inventar especificações não
      visíveis nem informadas (trecho do prompt legível no código, não é preciso testar a
      qualidade semântica de forma automatizada).
- [ ] Resposta da IA com algum campo faltando, com tipo errado, ou com `palavras_chave` que
      não é uma lista, levanta `ErroGeracaoAnuncio` com mensagem clara — a função nunca
      retorna um dict incompleto/malformado silenciosamente.
- [ ] `construir_data_uri` (ou equivalente) não está duplicada entre `app.py` e
      `gerador_anuncio.py` — existe em um único lugar e é importada onde for necessária.
- [ ] `python -m py_compile Local_AI/estudio_shopee/gerador_anuncio.py` executa sem erro.
- [ ] Nas Notas de execução, documente como a função foi exercitada: chamada real (se havia
      `OPENAI_API_KEY` disponível no ambiente do executor) OU, na ausência de chave, um teste
      manual local da etapa de VALIDAÇÃO/parsing com uma resposta simulada (sem rede), para
      provar que o schema e os erros funcionam como esperado.

## Notas de execução


## Verificação


## Revisão
