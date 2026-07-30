# 📚 ECC Studio Vision v5.0 — Documentação Técnica Oficial

## Visão Geral

O ECC Studio Vision é uma aplicação Streamlit para geração de imagens profissionais de produtos utilizando:

- Processamento local com Rembg (remoção de fundo)
- LiteLLM para geração de prompts
- RunPod para renderização final
- Memória de estilos aprovada pelo usuário

A aplicação foi projetada principalmente para produtos impressos em 3D.

---

# Arquitetura

Fluxo interno:

Imagem → Rembg (opcional) → LiteLLM → Prompt Final → RunPod → Imagem Gerada → Aprovação → Memória

---

# Dependências

```bash
pip install streamlit requests pillow rembg[cpu]
```

Também é necessário:

- LiteLLM instalado
- config.yaml configurado
- Endpoint Serverless no RunPod

---

# Configuração

No início do arquivo `app.py` devem ser configurados:

```python
RUNPOD_API_KEY = "SUA_CHAVE"
ENDPOINT_ID = "SEU_ENDPOINT"
```

Também deve ser ajustado:

```python
COMANDO_LITELLM
```

para apontar para a instalação correta do LiteLLM.

---

# Inicialização

Executar:

```bash
streamlit run app.py
```

O sistema:

1. Inicia a interface Streamlit.
2. Verifica se o LiteLLM está rodando na porta 8000.
3. Caso não esteja, inicia automaticamente o LiteLLM.

---

# Estrutura Criada Automaticamente

Na primeira execução:

```text
fotos_prontas/
```

Também são utilizados:

```text
memoria_catalogo.txt
memoria_ambiente.txt
memoria_mao.txt
```

---

# Perfis de Memória

Existem três perfis independentes:

| Perfil | Arquivo |
|----------|----------|
| Catálogo | memoria_catalogo.txt |
| Ambiente | memoria_ambiente.txt |
| Lifestyle | memoria_mao.txt |

Quando uma imagem é aprovada:

- o prompt utilizado é salvo;
- apenas os 3 prompts mais recentes são utilizados como referência futura.

---

# Fluxo de Operação

## Etapa 1 — Upload

Formatos aceitos:

- PNG
- JPG
- JPEG

A interface aceita:

### Print do Fatiador

Utilizado quando a peça já está limpa.

Recomendado:

- ocultar grade (grid)
- ocultar eixos

### Foto Real

Utilizado quando a peça foi fotografada.

Neste modo aparece:

```text
✂️ Processar Recorte Local (Custo $0)
```

Ao clicar:

1. O Rembg remove o fundo.
2. É criado um fundo branco.
3. A imagem fica pronta para renderização.

---

## Etapa 2 — Configuração

Campos obrigatórios:

- Produto
- Cor/Material

Estilos disponíveis:

### Catálogo

Prompt adicional:

```text
Use pure infinite solid white background.
Completely isolated product shot.
```

Memória utilizada:

```text
catalogo
```

### Ambiente

Permite informar um cenário personalizado.

Memória utilizada:

```text
ambiente
```

### Lifestyle

Adiciona instruções para geração de mão segurando o produto.

Memória utilizada:

```text
mao
```

---

## Etapa 3 — Geração

Ao clicar:

```text
🚀 Enviar para Renderização (Custo API)
```

O sistema:

1. Converte a imagem para Base64.
2. Recupera a memória do perfil.
3. Monta o histórico do LLM.
4. Solicita um prompt ao LiteLLM.
5. Envia prompt + imagem para o RunPod.
6. Recebe a imagem gerada.

---

# Diretrizes Internas do Prompt

O sistema força automaticamente:

- aparência fotográfica profissional;
- iluminação de estúdio;
- lente macro 85mm;
- acabamento de polímero fosco;
- leves linhas de impressão 3D;
- remoção de grids e elementos de interface;
- prevenção de mãos deformadas;
- prevenção de marcas d'água;
- prevenção de textos.

Essas regras são embutidas no código e não precisam ser informadas pelo usuário.

---

# Refinamento

Após a geração:

```text
🛠️ Recalcular Ajuste
```

permite informar alterações.

Exemplo:

```text
Deixe a iluminação mais suave.
```

O sistema:

1. mantém a geometria original;
2. gera um novo prompt;
3. solicita nova renderização ao RunPod.

Cada nova renderização incrementa a versão.

---

# Aprovação

Botão:

```text
✅ Aprovar e Salvar
```

Ao aprovar:

1. A imagem é salva.
2. O prompt é armazenado na memória.

Formato de salvamento:

```text
fotos_prontas/render_TIMESTAMP_vVERSAO.png
```

Exemplo:

```text
fotos_prontas/render_1750760000_v2.png
```

Importante:

O código NÃO preserva o nome original do arquivo enviado.

---

# Anúncio Shopee (Etapa 4 — feature nova)

> Nota: esta seção documenta uma função adicionada depois da v5.0 descrita no resto deste
> documento (T-001 a T-004 da fábrica de software). Só existe na aba "🎨 Gerador
> Automático" (com custo de API) — o "📋 Modo Gratuito" não tem essa etapa, porque ali a
> imagem final é gerada fora do app e o Estúdio nunca recebe seus bytes.

## Quando aparece

Assim que existe uma imagem final na Mesa de Refinamento (Etapa 3) — ou seja, depois de
clicar no botão de gerar as variações (rótulo dinâmico, no formato "🚀 Gerar Nx com
<motor> (~$custo)", ex.: "🚀 Gerar 2x com Nano Banana Pro (~$0.090)") e a renderização
concluir —, surge a seção "4. Anúncio Shopee", logo abaixo dos botões "🛠️ Recalcular
Ajuste" / "✅ Aprovar Catálogo".

## O que é gerado

Ao clicar em `📝 Gerar Anúncio Completo`:

1. A MESMA imagem final exibida na Mesa de Refinamento (a que seria salva ao aprovar) é
   enviada, em base64, junto com o contexto textual já preenchido na Etapa 2 (produto,
   cor/material, estilo escolhido e eventual instrução/cenário customizado).
2. Essa imagem + contexto vão para um modelo de IA com visão (chamada HTTP direta à API
   OpenAI, JSON mode — ver `gerador_anuncio.py`; modelo configurável pela variável
   `OPENAI_MODEL_ANUNCIO` em `CHAVES.env`, padrão `gpt-5.6-luna`).
3. A IA devolve três campos: **título** (otimizado para busca e conversão na Shopee),
   **descrição** estruturada (abertura, benefícios, especificações visíveis, chamada para
   ação) e **palavras-chave** sugeridas — sempre em português (BR), e sempre baseados
   apenas no que é visível na foto e no que foi informado no contexto (a IA é instruída a
   nunca inventar especificação não visível/não informada).

## Como editar

Título e descrição aparecem em campos editáveis (`Título do anúncio` e `Descrição do
anúncio`, com contador de caracteres no título) logo abaixo do botão — o texto pode ser
ajustado livremente antes de aprovar. As palavras-chave sugeridas aparecem como legenda,
somente leitura.

## Onde é salvo

Ao clicar em `✅ Aprovar Catálogo` (o mesmo botão que salva a imagem), se houver um
anúncio gerado, ele é salvo em `fotos_prontas/` com o MESMO nome-base do render, trocando
só a extensão:

```text
fotos_prontas/render_TIMESTAMP_vVERSAO.png   (imagem, como já era)
fotos_prontas/render_TIMESTAMP_vVERSAO.txt   (anúncio: Título / Descrição / Palavras-chave)
```

O `.txt` reflete o valor ATUAL dos campos editáveis no momento do clique (ou seja,
qualquer edição manual feita antes de aprovar é o que vai para o arquivo, não o texto
originalmente sugerido pela IA). Se nenhum anúncio foi gerado para aquela imagem, só o
`.png` é salvo — a etapa é opcional, o resto do fluxo (edição/aprovação de imagem)
funciona normalmente sem ela.

## Erros

Falha ao gerar (rede fora do ar, `OPENAI_API_KEY` ausente/inválida, resposta da IA fora
do formato esperado) aparece como uma mensagem de erro (`❌ ...`) dentro da própria seção
"4. Anúncio Shopee" (logo abaixo do botão de gerar, antes dos campos editáveis), sem
derrubar a aba — o restante do fluxo do Estúdio (refinamento, aprovação de imagem)
continua funcionando normalmente mesmo se o anúncio falhar.

---

# Limpeza de Memória

Na barra lateral:

```text
🧨 Resetar Catálogo (Branco)
🧨 Resetar Ambientes
🧨 Resetar Lifestyle (Mãos)
```

Esses botões removem completamente os arquivos de memória correspondentes.

---

# Limitações Atuais

O código atual NÃO possui:

- processamento automático da pasta pecas_brutas;
- monitoramento de diretórios;
- renderização em lote;
- leitura automática de diretrizes_de_imagem.md;
- salvamento utilizando o nome original do arquivo.

Esses recursos aparecem na documentação antiga como proposta de fluxo, mas não estão implementados no código enviado.

---

# Boas Práticas

1. Utilize imagens bem iluminadas.
2. Remova grades do fatiador.
3. Valide o recorte antes de renderizar.
4. Aguarde o endpoint do RunPod aquecer no primeiro uso do dia.
5. Para Lifestyle, utilize imagens compatíveis com uma pegada natural.

---

# Encerramento

Para encerrar corretamente:

```text
CTRL + C
```

no terminal onde o Streamlit foi iniciado.

---
