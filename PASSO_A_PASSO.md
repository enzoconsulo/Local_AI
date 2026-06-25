# Guia de Configuração: Infraestrutura de IA Híbrida (LiteLLM)

Este guia fornece um passo a passo para configurar uma infraestrutura de IA utilizando o LiteLLM como roteador, permitindo alternar entre modelos locais (Ollama) e provedores em nuvem (Groq/RunPod).

## 1. Pré-requisitos

- Python 3.12 ou superior instalado
- VS Code instalado
- Chaves de API ativas (Groq e RunPod)

## 2. Instalação do LiteLLM

No terminal, na pasta do seu projeto, instale o pacote proxy:

```bash
pip install 'litellm[proxy]'
```

## 3. Configuração do `config.yaml`

Crie um arquivo chamado `config.yaml` na raiz do projeto:

```yaml
model_list:
  # Modelo Local (Ollama)
  - model_name: qwen-local
    litellm_params:
      model: ollama/qwen2.5-coder:1.5b
      api_base: http://localhost:11434

  # Modelo Rápido em Nuvem (Groq)
  - model_name: chat-rapido
    litellm_params:
      model: groq/llama-3.3-70b-versatile
      api_key: "SUA_CHAVE_GROQ_AQUI"

  # Modelo de Alta Capacidade (RunPod)
  - model_name: arquiteto-pesado
    litellm_params:
      model: openai/Qwen/Qwen2.5-Coder-7B-Instruct
      api_base: "SUA_URL_RUNPOD_AQUI"
      api_key: "SUA_CHAVE_RUNPOD_AQUI"

router_settings:
  routing_strategy: usage-based-routing
```

## 4. Executando o Servidor

Para iniciar o roteador, rode no terminal:

```bash
litellm --config config.yaml --port 8000

or 

C:\Users\enzoconsulo\AppData\Local\Programs\Python\Python313\Scripts\litellm.exe --config config.yaml --port 8000
```

## 5. Integração no VS Code (Continue)

No arquivo de configuração da extensão Continue (`config.yaml` ou `config.json`):

```yaml
models:
  - name: Chat Hibrido (LiteLLM)
    provider: openai
    model: chat-rapido
    apiBase: http://localhost:8000
    roles:
      - chat
      - edit
      - apply
```

## 6. Dicas de Segurança

- **Não versionar chaves:** Nunca suba o arquivo com as chaves reais para o GitHub. Use variáveis de ambiente (`os.environ/NOME_DA_VARIAVEL`) no arquivo YAML.
- **Manutenção:** Se a Groq descontinuar um modelo, basta atualizar o nome do modelo no `config.yaml` conforme a mensagem de erro que aparecer no terminal.
