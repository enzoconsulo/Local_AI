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
