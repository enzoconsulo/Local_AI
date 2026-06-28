"""
Bootstrap Dinâmico e Unificado para o LiteLLM

O que este script faz a CADA execução:
1. Carrega as variáveis do arquivo CHAVES.env localmente.
2. Filtra espaços e comentários invisíveis que corrompem as chaves.
3. Valida se as chaves (GROQ, RUNPOD) existem.
4. SEMPRE recria o arquivo config.yaml usando injeção segura de memória.
5. Encontra o executável do LiteLLM de forma automática e inicia na porta 8000.
"""

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / "CHAVES.env"
CONFIG_FILE = BASE_DIR / "config.yaml"

def carregar_env():
    """Lê o arquivo CHAVES.env de forma nativa e injeta no ambiente com blindagem."""
    if not ENV_FILE.exists():
        raise FileNotFoundError(f"🚨 Arquivo não encontrado: {ENV_FILE}\nCrie um arquivo chamado CHAVES.env com as chaves necessárias.")
    
    env_data = {}
    for linha in ENV_FILE.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        # Ignora linhas vazias ou comentários
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        
        chave, valor = linha.split("=", 1)
        chave = chave.strip()
        
        # BLINDAGEM: Remove comentários inline (ex: GROQ=gsk_123 # chave do groq)
        valor = valor.split("#")[0]
        
        # BLINDAGEM: Remove espaços em branco e aspas acidentais
        valor = valor.strip().strip("'").strip('"')
        
        env_data[chave] = valor
        os.environ[chave] = valor # Injeta na memória do processo atual
        
    return env_data

def validar_chaves():
    """Garante que todas as chaves essenciais para a configuração estão disponíveis."""
    chaves_obrigatorias = ["GROQ", "RUNPOD_KEY", "ENDPOINT_ID_RUNPOD_vLLM", "ENDPOINT_ID_RUNPOD_DADOS"]
    chaves_faltando = [k for k in chaves_obrigatorias if not os.getenv(k)]
    
    if chaves_faltando:
        raise SystemExit(f"🚨 ERRO: As seguintes variáveis não foram encontradas no CHAVES.env: {', '.join(chaves_faltando)}")

def gerar_config_yaml():
    """Recria o config.yaml usando a sintaxe segura do LiteLLM (os.environ)."""
    endpoint_img = os.getenv("ENDPOINT_ID_RUNPOD_vLLM")
    endpoint_dados = os.getenv("ENDPOINT_ID_RUNPOD_DADOS")
    
    # Ao usar "os.environ/NOME_DA_CHAVE", o LiteLLM puxa direto da RAM,
    # evitando erros de sintaxe no YAML causados por aspas ou caracteres especiais da chave.
    config_text = f"""model_list:
  # 1. O Autocomplete / Chat Local (Opcional - Seu PC)
  - model_name: qwen-local
    litellm_params:
      model: ollama/qwen2.5-coder:1.5b
      api_base: http://localhost:11434

  # 2. O Chat Gratuito Rápido (Groq - Atualizado)
  - model_name: chat-rapido
    litellm_params:
      model: groq/llama-3.3-70b-versatile
      api_key: "os.environ/GROQ"

  # 3. O Arquiteto Pesado de Imagens (RunPod)
  - model_name: arquiteto-pesado
    litellm_params:
      model: openai/Qwen/Qwen2.5-Coder-7B-Instruct
      api_base: "https://api.runpod.ai/v2/{endpoint_img}/openai/v1"
      api_key: "os.environ/RUNPOD_KEY"

  # 4. O Cérebro Analítico de Dados (RunPod - Qwen 32B AWQ)
  - model_name: cerebro-dados
    litellm_params:
      model: openai/Qwen/Qwen2.5-32B-Instruct-AWQ
      api_base: "https://api.runpod.ai/v2/{endpoint_dados}/openai/v1"
      api_key: "os.environ/RUNPOD_KEY"

# leitura do MicroSD:
embeddingsProvider:
  provider: ollama
  model: nomic-embed-text
  apiBase: http://localhost:11434

router_settings:
  routing_strategy: usage-based-routing
"""
    CONFIG_FILE.write_text(config_text, encoding="utf-8")
    print(f"✅ Arquivo de configuração recriado dinamicamente em: {CONFIG_FILE.name}")

def iniciar_litellm():
    """Encontra o LiteLLM de forma elegante e roda o servidor."""
    # Busca o comando no sistema de forma limpa
    litellm_exe = shutil.which("litellm")
    
    if not litellm_exe:
        # Fallback de segurança: procura na pasta de Scripts do Python atual
        pasta_scripts = Path(sys.executable).parent / "Scripts"
        litellm_path = pasta_scripts / "litellm.exe"
        if litellm_path.exists():
            litellm_exe = str(litellm_path)
        else:
            raise SystemExit("🚨 ERRO: Comando 'litellm' não encontrado. Execute 'pip install litellm' antes de iniciar.")

    cmd = [litellm_exe, "--config", str(CONFIG_FILE), "--port", "8000"]
    print("\n🚀 Iniciando Motor Multi-Modelo LiteLLM (Porta 8000)...")
    print(f"Comando Executado: {' '.join(shlex.quote(p) for p in cmd)}\n")

    try:
        # Roda o processo e trava o terminal aqui enquanto o servidor estiver ligado
        process = subprocess.Popen(cmd, cwd=str(BASE_DIR))
        return process.wait()
    except KeyboardInterrupt:
        print("\n[🔌] LiteLLM encerrado com segurança pelo usuário.")
        return 130

def main():
    print("Iniciando Bootstrap do Sistema Híbrido de IA...\n")
    
    try:
        carregar_env()
        validar_chaves()
    except Exception as e:
        print(e)
        sys.exit(1)

    print("✅ Variáveis de ambiente carregadas e higienizadas com sucesso.")

    # Ação unificada: SEMPRE escreve o config e SEMPRE inicia.
    gerar_config_yaml()
    codigo_saida = iniciar_litellm()
    
    sys.exit(codigo_saida)

if __name__ == "__main__":
    main()