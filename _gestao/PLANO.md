# Plano — ia-hibrida-limpa

Escopo desta rodada: a função de "Anúncio completo" no Estúdio (`estudio_shopee`) — ver
`ESPECIFICACAO.md`. Constrói-se de dentro para fora: primeiro o motor de geração (backend,
testável sem Streamlit), depois a integração na UI e a persistência, por fim testes
automatizados e documentação.

## Fase 1 — Fundação
Meta: o motor de geração de anúncio (`gerador_anuncio.py`) funciona ponta a ponta — recebe
imagem + contexto do produto e devolve `{titulo, descricao, palavras_chave}` em JSON
validado, com erro claro em qualquer falha (chave ausente, rede, schema).
Marco: aprovado 2026-07-28 (testador em modo marco: 10 cenários ponta a ponta, 10/10, com
rede mockada e sem gastar API real — inclui os quatro caminhos de erro exigidos pela meta:
credencial ausente, falha de rede, schema malformado e conteúdo nulo por recusa)
Tarefas: T-001, T-002

## Fase 2 — Núcleo
Meta: dentro do Estúdio, o usuário consegue gerar o anúncio a partir da imagem final, editar
título/descrição na tela, e ter tudo salvo junto do render ao aprovar o catálogo.
Marco: aprovado 2026-07-30 (testador em modo marco: fluxo ponta a ponta com
streamlit.testing.v1.AppTest — geração mockada, edição de título/descrição refletida no
`.txt` salvo com o mesmo nome-base do `.png`, fluxo sem anúncio sem regressão; suíte
`tests/test_gerador_anuncio.py` 5/5 e `py_compile` limpos)
Tarefas: T-003, T-004

## Fase 3 — Refinamento
Meta: motor de geração coberto por testes automatizados (sem custo de API real) e
documentação do Estúdio e do projeto refletindo a função nova.
Marco: aprovado 2026-07-30 (testador em modo marco: suíte `test_gerador_anuncio.py` 5/5,
0.25s, sem custo de API real; documentação de `how_to_use.md` e `CLAUDE.md` do projeto
conferida contra o código real — 14 afirmações checadas, todas batendo)
Tarefas: T-005, T-006

<!-- Linha "Marco:": o orquestrador registra ali o resultado da verificação de fase —
     pendente | aprovado AAAA-MM-DD | reprovado AAAA-MM-DD (correções: T-NNN, ...) -->
