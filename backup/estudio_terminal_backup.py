import base64
import requests
import json
import os
import time
import subprocess
import socket
import sys

# ================= CONFIGURAÇÕES GERAIS =================
RUNPOD_API_KEY = "SUA_CHAVE_RUNPOD_AQUI"
ENDPOINT_ID = "SEU_ENDPOINT_ID_AQUI"
URL_RUNPOD = f"https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync"

URL_LITELLM = "http://localhost:8000/v1/chat/completions"
MODELO_TEXTO = "chat-rapido" 
COMANDO_LITELLM = r"C:\Users\enzoconsulo\AppData\Local\Programs\Python\Python313\Scripts\litellm.exe --config config.yaml --port 8000"

PASTA_ENTRADA = "pecas_brutas"
PASTA_SAIDA = "fotos_prontas"
ARQUIVO_MEMORIA = "memoria_estilo.txt"

os.makedirs(PASTA_ENTRADA, exist_ok=True)
os.makedirs(PASTA_SAIDA, exist_ok=True)

# ================= INFRAESTRUTURA DE BACKGROUND =================
def verificar_porta(porta=8000):
    """Verifica se o roteador de IA local já está ativo."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', porta)) == 0

def iniciar_litellm_background():
    """Acorda a IA de texto silenciosamente."""
    if verificar_porta():
        return None
    print(" [⏳] Iniciando Motor de Inteligência Local no background...")
    processo = subprocess.Popen(
        COMANDO_LITELLM, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    for _ in range(15):
        if verificar_porta(): return processo
        time.sleep(1)
    print(" [!] Falha crítica: O LiteLLM não iniciou. Verifique o caminho do executável.")
    sys.exit(1)

# ================= MEMÓRIA DE ESTILO (IN-CONTEXT LEARNING) =================
def salvar_sucesso(prompt_aprovado):
    """Salva o prompt que você gostou no banco de memória."""
    with open(ARQUIVO_MEMORIA, "a", encoding="utf-8") as f:
        f.write(prompt_aprovado + "\n")

def carregar_memoria_recente():
    """Lê os últimos 3 sucessos para ensinar a IA o seu estilo."""
    if not os.path.exists(ARQUIVO_MEMORIA):
        return "Ainda não há exemplos de estilo aprovados pelo usuário. Siga as instruções base."
    
    with open(ARQUIVO_MEMORIA, "r", encoding="utf-8") as f:
        linhas = f.readlines()
        
    ultimos_sucessos = [linha.strip() for linha in linhas[-3:] if linha.strip()]
    if not ultimos_sucessos:
        return "Ainda não há exemplos de estilo aprovados pelo usuário. Siga as instruções base."
        
    memoria_formatada = "\n".join([f"- {p}" for p in ultimos_sucessos])
    return f"Here are the last 3 prompts approved by the user. Mimic this exact style, tone, and formatting:\n{memoria_formatada}"

# ================= DIRETOR DE ARTE (IA DE TEXTO) =================
DIRETRIZES_SISTEMA = """
You are a Senior E-commerce Art Director specialized in 3D printed products. Your job is to translate the user's idea into the PERFECT prompt for Stable Diffusion.

Follow this EXACT formula to build the prompt:
[Subject] + [Material/Texture] + [Surface/Desk] + [Background Environment] + [Lighting] + [Camera setup] + [Quality tags]

Rules:
1. ALWAYS add texture keywords: "subtle 3D printing horizontal layer lines, matte polymer finish, realistic plastic".
2. If the user asks for a "white background" or "cutout", use: "isolated on pure infinite white background, clean white acrylic surface".
3. If the user describes a scene, translate it into high-end photography terms (e.g., "dark carbon fiber desk surface, blurred neon gaming setup in background").
4. ALWAYS add: "commercial studio lighting, 85mm macro lens, sharp focus, 8k resolution, photorealistic, product photography".
5. OUTPUT ONLY THE PROMPT. English only. Comma-separated words. No explanations.
"""

def chamar_diretor_de_arte(historico_mensagens):
    payload = {"model": MODELO_TEXTO, "messages": historico_mensagens, "temperature": 0.5}
    print(" ├── 🧠 Traduzindo sua ideia e checando memória de estilo...")
    try:
        resposta = requests.post(URL_LITELLM, json=payload, timeout=15)
        resposta.raise_for_status()
        return resposta.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"\n [!] Falha de comunicação com o LiteLLM: {e}")
        sys.exit(1)

# ================= RENDERIZADOR (RUNPOD - CONFIG SHOPEE) =================
def renderizar_imagem(imagem_b64, prompt_visual):
    payload = {
        "input": {
            "api_name": "txt2img",
            "prompt": prompt_visual,
            "negative_prompt": "3d render, CGI, cartoon, sketch, drawing, illustration, watermark, text, signature, logo, blurry, ugly, deformed, glossy, metallic, low resolution, badly lit, harsh shadows, dirty",
            "sampler_name": "DPM++ 2M Karras",
            "steps": 35, # Ponto Doce para texturas 3D
            "cfg_scale": 7.0,
            "width": 1024, # Padrão Ouro Shopee 1:1
            "height": 1024,
            "alwayson_scripts": {
                "controlnet": {
                    "args": [{
                        "input_image": imagem_b64,
                        "module": "canny",
                        "model": "control_v11p_sd15_canny [d14c016b]",
                        "weight": 1.0, # Respeito incondicional à geometria do seu STL
                        "control_mode": 0,
                        "resize_mode": 1
                    }]
                }
            }
        }
    }
    headers = {"Authorization": f"Bearer {RUNPOD_API_KEY}", "Content-Type": "application/json"}
    
    print(" ├── 🚀 Renderizando na Nuvem (RTX 4000/3090)...")
    try:
        response = requests.post(URL_RUNPOD, headers=headers, json=payload, timeout=180)
        response.raise_for_status()
        res = response.json()
        if 'output' in res and 'images' in res['output']:
            return res['output']['images'][0]
        return None
    except Exception as e:
        print(f"\n [!] Erro de renderização: {e}")
        return None

# ================= INTERFACE PRINCIPAL =================
def limpar_tela():
    os.system('cls' if os.name == 'nt' else 'clear')

def main():
    limpar_tela()
    print("=====================================================")
    print("    ECC STUDIO VISION - ULTIMATE CORE v3.5 (MEMÓRIA) ")
    print("=====================================================")
    
    proc_litellm = iniciar_litellm_background()
    print(" [+] Infraestrutura Híbrida: PRONTA\n")

    try:
        arquivos = [f for f in os.listdir(PASTA_ENTRADA) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        if not arquivos:
            print(" [Aviso] A mesa de trabalho está vazia.")
            print(" -> Coloque um print do fatiador na pasta 'pecas_brutas' e reinicie o sistema.")
            return

        for idx, arq in enumerate(arquivos):
            print(f"      [{idx}] {arq}")
            
        print("-" * 53)
        escolha = int(input(" > Selecione a peça (Nº): "))
        arq_base = arquivos[escolha]
        
        with open(os.path.join(PASTA_ENTRADA, arq_base), "rb") as f:
            b64_base = base64.b64encode(f.read()).decode('utf-8')

        # Interrogatório de Setup
        produto = input(f"\n > 1. O que é o produto? (Ex: Suporte de parede): ")
        cor_filamento = input(f" > 2. Qual a cor e material? (Ex: PETG Preto Fosco): ")
        
        print("\n > 3. Estilo de Fundo:")
        print("   [1] Fundo Branco Puro (Recorte para Catálogo Shopee)")
        print("   [2] Construir Cenário Personalizado")
        estilo_opc = input(" > Escolha [1] ou [2]: ")
        
        if estilo_opc == '1':
            instrucao_fundo = "Use a pure, infinite solid white background. Completely isolated product shot, no distractions, studio lighting."
        else:
            ideia_cenario = input("   > Descreva o cenário (Ex: Mesa de madeira rústica com ferramentas): ")
            instrucao_fundo = f"Place it in a realistic, highly detailed environment based on this idea: '{ideia_cenario}'"

        comando_final = f"Product: {produto}. Material and Color: {cor_filamento}. Background instruction: {instrucao_fundo}."
        
        # Injeção de Memória nas Diretrizes
        memoria_estilo = carregar_memoria_recente()
        diretriz_com_memoria = f"{DIRETRIZES_SISTEMA}\n\n[USER APPROVED STYLE EXAMPLES]\n{memoria_estilo}"
        
        hist = [
            {"role": "system", "content": diretriz_com_memoria},
            {"role": "user", "content": comando_final}
        ]

        versao = 1
        while True:
            print(f"\n[ 📸 PRODUZINDO ANÚNCIO - VERSÃO {versao} ]")
            prompt = chamar_diretor_de_arte(hist)
            print(f" ├── 📝 Prompt: {prompt[:85]}...")
            
            img_final = renderizar_imagem(b64_base, prompt)
            
            if img_final:
                saida = os.path.join(PASTA_SAIDA, f"v{versao}_{arq_base.split('.')[0]}.png")
                with open(saida, "wb") as f:
                    f.write(base64.b64decode(img_final))
                print(f" └── ✅ SUCESSO! Foto salva em -> {saida}")
            else:
                print(" └── ❌ Falha na API da Nuvem.")

            print("\n" + "="*53)
            print(" [1] Aprovar, Salvar na Memória e Sair")
            print(" [2] Ajustar Fundo/Luz (Ex: 'Deixe a mesa mais clara')")
            acao = input(" > O que deseja fazer? ")
            
            if acao == '1':
                salvar_sucesso(prompt)
                print(" [🧠] Estilo salvo na memória com sucesso!")
                break
            else:
                ajuste = input(" > O que quer mudar? ")
                hist.append({"role": "assistant", "content": prompt})
                hist.append({"role": "user", "content": f"Keep the exact same product and angle, but apply this change: {ajuste}"})
                versao += 1

    except Exception as e:
        print(f"\n [!] Erro inesperado: {e}")
    finally:
        if proc_litellm:
            print("\n [🔌] Limpando processos de fundo...")
            proc_litellm.terminate()
        print(" [✨] Sistema encerrado com segurança.")

if __name__ == "__main__":
    main()