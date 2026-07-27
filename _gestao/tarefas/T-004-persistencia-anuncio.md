---
id: T-004
titulo: Salvar o anúncio junto do render aprovado
projeto: ia-hibrida-limpa
status: backlog
prioridade: media
dependencias: [T-003]
areas: [Local_AI/estudio_shopee/app.py]
tentativas: 0
agente: streamlit-ui
criada: 2026-07-27
atualizada: 2026-07-27
---

## Objetivo
Ao aprovar o catálogo (fluxo já existente do Estúdio), salvar o anúncio atual (título,
descrição, palavras-chave — já com eventuais edições manuais do usuário) junto do arquivo de
imagem em `fotos_prontas/`.

## Contexto
- Leia o handler do botão "✅ Aprovar Catálogo" em `Local_AI/estudio_shopee/app.py` — hoje
  ele salva `bytes_imagem` em
  `CURRENT_DIR / "fotos_prontas" / f"render_{int(time.time())}_v{st.session_state.versao}.png"`
  e chama `salvar_memoria(...)`.
- Salve o anúncio (se `st.session_state.anuncio_atual` estiver preenchido) num arquivo com o
  MESMO nome-base do PNG salvo (ex.: `render_<timestamp>_v<versao>.txt`), na mesma pasta
  `fotos_prontas/`, contendo título, descrição e palavras-chave de forma legível (texto
  simples é suficiente — mesmo espírito de `memoria_*.txt`, que também é texto plano).
  Use os valores ATUAIS de `st.session_state.anuncio_atual` (refletindo qualquer edição
  manual feita nos campos de T-003), não um valor "original" separado.
- Se `st.session_state.anuncio_atual` for `None` (usuário aprovou sem gerar/preencher
  anúncio), o comportamento deve ser IDÊNTICO ao de hoje — nenhuma regressão no fluxo
  existente, nenhum arquivo vazio ou quebrado criado.

## Critérios de aceite
- [ ] Aprovar o catálogo com um anúncio presente cria um arquivo em `fotos_prontas/` com o
      mesmo timestamp/versão do PNG salvo na mesma aprovação.
- [ ] O arquivo contém título, descrição e palavras-chave, nos valores atuais dos campos
      editáveis (não os valores originais da IA, se houve edição manual).
- [ ] Aprovar o catálogo SEM anúncio gerado (`anuncio_atual is None`) continua funcionando
      exatamente como antes — mesmo PNG salvo, mesma chamada a `salvar_memoria`, nenhum
      arquivo de anúncio extra criado.
- [ ] `python -m py_compile Local_AI/estudio_shopee/app.py` executa sem erro.

## Notas de execução


## Verificação


## Revisão
