---
id: T-003
titulo: UI — seção "Anúncio Shopee" na aba de criar imagens
projeto: ia-hibrida-limpa
status: backlog
prioridade: alta
dependencias: [T-002]
areas: [Local_AI/estudio_shopee/app.py]
tentativas: 0
agente: streamlit-ui
criada: 2026-07-27
atualizada: 2026-07-27
---

## Objetivo
Adicionar, na aba "🎨 Gerador Automático" do Estúdio, uma seção que permite gerar o anúncio
completo (título + descrição + palavras-chave) a partir da imagem final selecionada, e editar
o resultado antes de usar.

## Contexto
- Leia `Local_AI/estudio_shopee/app.py` inteiro antes de editar — em especial a "Mesa de
  Refinamento" (`col2`, dentro de `aba_auto`) e o bloco de inicialização de
  `st.session_state` no topo do arquivo.
- Use `gerar_anuncio_shopee` e `ErroGeracaoAnuncio` de `gerador_anuncio.py` (T-002).
- Onde encaixar: dentro de `col2`, como uma nova seção (ex.: "4. Anúncio Shopee"), visível
  quando `st.session_state.imagem_gerada_b64` estiver preenchido (mesma condição já usada
  para mostrar "Ver Roteiro Operacional da IA" e o botão "✅ Aprovar Catálogo").
- Novo estado: `st.session_state.anuncio_atual` — inicialize como `None` junto aos demais
  `if 'x' not in st.session_state: st.session_state.x = ...` do topo do arquivo. Estrutura
  sugerida: `{"titulo": str, "descricao": str, "palavras_chave": list[str]}`.
- IMPORTANTE — reset de estado: quando o usuário troca de arquivo de upload (bloco que já
  reseta `img_recortada_bytes`, `imagem_gerada_b64`, `candidatos_atual`,
  `imagem_referencia_atual`, `prompt_manual`) ou gera uma nova imagem do zero (botão "🚀
  Gerar..."), resete também `st.session_state.anuncio_atual = None` — senão um anúncio antigo
  fica colado numa imagem nova.
- Botão "📝 Gerar Anúncio Completo": chama `gerar_anuncio_shopee(bytes_imagem, contexto)`,
  onde `bytes_imagem` é a imagem final atual (mesma variável já usada para exibir/aprovar o
  catálogo, ex. `bytes_imagem = base64.b64decode(st.session_state.imagem_gerada_b64)`) e
  `contexto` é montado a partir de `st.session_state.dados_atual` (produto, cor, estilo).
  Use `st.status`/`st.spinner` com mensagem em português durante a chamada, seguindo o padrão
  já usado nos outros botões de IA do arquivo (ex. "🚀 Gerar..." e "🛠️ Recalcular Ajuste").
- Em caso de `ErroGeracaoAnuncio`, mostre `st.error(...)` com a mensagem, sem deixar a
  exceção subir e derrubar a página — o resto da aba deve continuar funcionando.
- Campos editáveis: `st.text_input` para o título (com contador de caracteres visível, ex.
  `st.caption(f"{len(titulo)} caracteres")`) e `st.text_area` para a descrição, ambos
  pré-preenchidos com `st.session_state.anuncio_atual` e escrevendo de volta nele a cada
  edição (para que T-004 leia sempre o valor mais atual ao salvar). Palavras-chave podem ser
  exibidas como texto simples (ex. separadas por vírgula) ou `st.multiselect`/lista — escolha
  o mais simples que funcione bem na UI.

## Critérios de aceite
- [ ] A seção "Anúncio Shopee" aparece na aba "Gerador Automático" assim que há uma imagem
      final selecionada, e não aparece antes disso.
- [ ] Clicar em "Gerar Anúncio Completo" chama `gerar_anuncio_shopee` com a imagem final em
      bytes + o contexto do produto atual, e preenche `st.session_state.anuncio_atual`.
- [ ] Título e descrição aparecem em campos editáveis, pré-preenchidos com o resultado da IA;
      editar os campos atualiza `st.session_state.anuncio_atual`.
- [ ] Simular uma falha (ex.: rodar sem `OPENAI_API_KEY` configurada) resulta em
      `st.error(...)` visível, e as demais seções da página continuam funcionando
      normalmente (upload, geração de imagem, aprovação do catálogo).
- [ ] `st.session_state.anuncio_atual` volta a `None` ao trocar de arquivo de upload ou ao
      gerar uma nova imagem (botão "🚀 Gerar...").
- [ ] `python -m py_compile Local_AI/estudio_shopee/app.py` executa sem erro.

## Notas de execução


## Verificação


## Revisão
