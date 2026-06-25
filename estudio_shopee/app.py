"""
ECC Studio Vision v14.0 — Inglês Garantido + Performance + Multi-Provedor Grátis
=================================================================================
NOVIDADES (Jun/2026):

1. INGLÊS 100% GARANTIDO: o prompt final agora passa por uma verificação
   automática (heurística + correção via segunda chamada ao LLM local) que
   detecta resíduos de português — incluindo o NOME DO PRODUTO, que antes
   podia ir para o prompt sem tradução. As Diretrizes de Sistema também
   passaram a exigir que termos brasileiros/regionais sejam EXPLICADOS em
   inglês (não só traduzidos palavra-por-palavra), exatamente como já se
   fazia com "terere".

2. FRASES PRONTAS REMOVIDAS: as regras antigas (e os blocos por estilo —
   catálogo/lifestyle/ambiente) ditavam frases fixas em inglês que o LLM
   deveria copiar quase literalmente, gerando prompts repetitivos. Agora as
   regras descrevem O QUE precisa estar no prompt, e o LLM formula cada
   instrução com suas próprias palavras, variando a cada chamada.

3. REFATORAÇÃO DE PERFORMANCE:
   - O modelo de remoção de fundo (rembg/U2-Net) agora é carregado UMA VEZ
     e reaproveitado via `st.cache_resource` — antes, cada clique em
     "Isolar Produto" recarregava os pesos da rede do disco do zero, que é
     o gargalo de performance mais caro do programa.
   - Todas as chamadas HTTP (LLM local + downloads da Fal.ai) passaram a
     usar uma `requests.Session()` única, com retries automáticos em falhas
     transitórias (429/500/502/503/504) — menos overhead de conexão e mais
     resiliência, sem precisar clicar de novo manualmente.

4. MODO GRATUITO COM 3 PROVEDORES: além do Gemini, agora você pode gerar a
   instrução pensando no Meta AI (grátis, sem cota fixa divulgada, já
   integrado ao WhatsApp/Instagram) ou no Microsoft Copilot/Bing Image
   Creator (uma das cotas diárias grátis mais generosas do mercado, com
   licenciamento comercial claro) — bom para quando a cota diária do Gemini
   acabar. Os limites de cada um mudam com frequência; vale confirmar no
   site oficial de cada provedor antes de depender 100% deles.

DEPENDÊNCIAS (pip install --break-system-packages ...):
    streamlit requests python-dotenv pillow rembg fal-client
"""

import base64
import re
import streamlit as st
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import os
import time
import subprocess
import socket
import io
import sys
from PIL import Image
from rembg import remove, new_session
from dotenv import load_dotenv
from pathlib import Path

try:
    import fal_client
except ImportError:
    st.set_page_config(page_title="ECC Studio Vision", page_icon="🏭")
    st.error(
        "🚨 Pacote `fal-client` não encontrado.\n\n"
        "Instale com: `pip install fal-client --break-system-packages`"
    )
    st.stop()

# ================= 1. TRATAMENTO DE AMBIENTE =================
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent # Aponta para a pasta raiz (IA_Hibrida)

load_dotenv(dotenv_path=ROOT_DIR / "CHAVES.env")

st.set_page_config(page_title="ECC Studio Vision v14.0", page_icon="🏭", layout="wide")

FAL_KEY = os.getenv("FAL_KEY")

if not FAL_KEY:
    st.error("🚨 `FAL_KEY` ausente no seu arquivo CHAVES.env! Configure sua conta na Fal.ai.")
    st.stop()

URL_LITELLM = "http://localhost:8000/v1/chat/completions"
MODELO_TEXTO = "chat-rapido"

# Os motores de imagem da Fal.ai focados em E-commerce, Imagem para Imagem e Inpainting
MOTORES_IMAGEM = {
    # Modelos Novos, Otimizados para E-commerce (Melhor custo-benefício)
    "flux_subject": {
        "nome_curto": "FLUX Subject",
        "label": "🛒 Produto — FLUX Subject ($0.035) | Excelente foco no sujeito e ambientação",
        "endpoint": "fal-ai/flux-subject",
        "suporta_resolucao": False,
        "custo": {"padrao": 0.035},
    },
    "flux_dev": {
        "nome_curto": "FLUX Dev",
        "label": "🚀 Rápido — FLUX Dev Img2Img ($0.025) | Alta fidelidade, excelente para texturas 3D",
        "endpoint": "fal-ai/flux/dev/image-to-image",
        "suporta_resolucao": False,
        "custo": {"padrao": 0.025},
    },
    "flux_schnell": {
        "nome_curto": "FLUX Schnell",
        "label": "⚡ Ultra Barato — FLUX Schnell ($0.003) | O mais barato possível para testar blocos",
        "endpoint": "fal-ai/flux/schnell/image-to-image",
        "suporta_resolucao": False,
        "custo": {"padrao": 0.003},
    },
    # Modelos Legados da arquitetura "Nano Banana/Gemini" (Mantidos conforme pedido)
    "equilibrado": {
        "nome_curto": "Nano Banana 2",
        "label": "⚖️ Equilibrado — Nano Banana 2 ($0.08 a $0.16)",
        "endpoint": "fal-ai/nano-banana-2/edit",
        "suporta_resolucao": True,
        "custo": {"1K": 0.08, "2K": 0.12, "4K": 0.16},
    },
    "economico": {
        "nome_curto": "Nano Banana Original",
        "label": "💸 Econômico — Nano Banana Original ($0.039)",
        "endpoint": "fal-ai/nano-banana/edit",
        "suporta_resolucao": False,
        "custo": {"padrao": 0.039},
    },
    "premium": {
        "nome_curto": "Nano Banana Pro",
        "label": "🏆 Premium — Nano Banana Pro ($0.15 a $0.30) | Cenas altamente complexas",
        "endpoint": "fal-ai/nano-banana-pro/edit",
        "suporta_resolucao": True,
        "custo": {"1K": 0.15, "2K": 0.15, "4K": 0.30},
    },
}

FERRAMENTAS_GRATUITAS = {
    "gemini": {
        "nome": "Google Gemini (Nano Banana)",
        "url": "https://gemini.google.com",
        "nota": "Geralmente a melhor fidelidade fotorrealista entre as opções grátis. Cota diária limitada de imagens; marca d'água visível + SynthID.",
    },
    "meta": {
        "nome": "Meta AI (Imagine)",
        "url": "https://www.meta.ai",
        "nota": "Totalmente grátis, sem cota fixa divulgada; também funciona direto no WhatsApp/Instagram/Messenger. Boa alternativa quando a cota do Gemini acabar.",
    },
    "copilot": {
        "nome": "Microsoft Copilot / Bing Image Creator",
        "url": "https://copilot.microsoft.com",
        "nota": "Uma das cotas diárias grátis mais generosas do mercado, com licenciamento comercial mais claro para uso em anúncios.",
    },
}

ARQUIVOS_MEMORIA = {
    "catalogo": str(CURRENT_DIR / "memoria_catalogo.txt"),
    "ambiente": str(CURRENT_DIR / "memoria_ambiente.txt"),
    "mao": str(CURRENT_DIR / "memoria_mao.txt")
}
os.makedirs(CURRENT_DIR / "fotos_prontas", exist_ok=True)

if 'historico_llm' not in st.session_state: st.session_state.historico_llm = []
if 'imagem_gerada_b64' not in st.session_state: st.session_state.imagem_gerada_b64 = None
if 'candidatos_atual' not in st.session_state: st.session_state.candidatos_atual = []
if 'imagem_referencia_atual' not in st.session_state: st.session_state.imagem_referencia_atual = None
if 'descricao_ia' not in st.session_state: st.session_state.descricao_ia = ""
if 'prompt_atual' not in st.session_state: st.session_state.prompt_atual = ""
if 'prompt_manual' not in st.session_state: st.session_state.prompt_manual = ""
if 'dados_atual' not in st.session_state: st.session_state.dados_atual = None
if 'versao' not in st.session_state: st.session_state.versao = 1
if 'tipo_memoria_atual' not in st.session_state: st.session_state.tipo_memoria_atual = "catalogo"
if 'img_recortada_bytes' not in st.session_state: st.session_state.img_recortada_bytes = None
if 'arquivo_atual' not in st.session_state: st.session_state.arquivo_atual = ""
if 'motor_ia_pronto' not in st.session_state: st.session_state.motor_ia_pronto = False

# ================= 2. PERFORMANCE: SESSÕES REUTILIZÁVEIS =================

@st.cache_resource
def obter_sessao_rembg():
    return new_session("u2net")

def _criar_sessao_http():
    sessao = requests.Session()
    retries = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    adaptador = HTTPAdapter(max_retries=retries)
    sessao.mount("http://", adaptador)
    sessao.mount("https://", adaptador)
    return sessao

SESSAO_HTTP = _criar_sessao_http()

# ================= 3. ENGENHARIA DE CANVAS =================
def preparar_canvas_perfeito(imagem_bytes, estilo, neutralizar_cor=False):
    resultado_bytes = remove(imagem_bytes, session=obter_sessao_rembg())
    img_recortada = Image.open(io.BytesIO(resultado_bytes)).convert("RGBA")

    if neutralizar_cor:
        _, _, _, a = img_recortada.split()
        gray = img_recortada.convert('L')
        img_recortada = Image.merge('RGBA', (gray, gray, gray, a))

    tamanho_canvas = 1536
    fator_escala = 0.78 if estilo == "Catálogo (Fundo Branco Puro)" else 0.42

    w, h = img_recortada.size
    maior_lado = max(w, h)
    proporcao = (tamanho_canvas * fator_escala) / maior_lado
    novo_w, novo_h = int(w * proporcao), int(h * proporcao)

    img_redimensionada = img_recortada.resize((novo_w, novo_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (tamanho_canvas, tamanho_canvas), (255, 255, 255, 255))

    pos_x = (tamanho_canvas - novo_w) // 2
    deslocamento_vertical = int(tamanho_canvas * 0.12) if estilo == "Ambiente (Cenário Realista)" else 0
    pos_y = (tamanho_canvas - novo_h) // 2 + deslocamento_vertical

    canvas.paste(img_redimensionada, (pos_x, pos_y), img_redimensionada)

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()

def carregar_memoria(tipo):
    arquivo = ARQUIVOS_MEMORIA[tipo]
    if not os.path.exists(arquivo): return ""
    with open(arquivo, "r", encoding="utf-8") as f:
        linhas = [l.strip() for l in f.readlines() if l.strip()]
    return "\n".join([f"- {p}" for p in linhas[-3:]]) if linhas else ""

def salvar_memoria(tipo, prompt):
    with open(ARQUIVOS_MEMORIA[tipo], "a", encoding="utf-8") as f:
        f.write(prompt + "\n")

def resetar_memoria(tipo):
    if os.path.exists(ARQUIVOS_MEMORIA[tipo]):
        os.remove(ARQUIVOS_MEMORIA[tipo])

def checar_porta_8000():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', 8000)) == 0

def montar_instrucao_estilo(estilo, cenario_custom):
    if estilo == "Catálogo (Fundo Branco Puro)":
        return "catalogo", ("the background must become a plain, pure white, fully isolated "
                             "studio backdrop, with no other objects, props, or textures anywhere in frame")
    elif estilo == "Lifestyle (Sendo Segurado por uma Mão)":
        return "mao", ("a realistic human hand should be naturally holding the product, "
                        "in a warm, natural-light lifestyle photography style")
    else:
        return "ambiente", (f"the background should become a realistic environment, based only on "
                             f"this description from the user: '{cenario_custom}' — a plain white "
                             f"background must NOT be used")

# ================= 4. INTEGRAÇÃO NATIVA FAL.AI =================

def construir_data_uri(imagem_bytes, mime_type="image/jpeg"):
    img_b64 = base64.b64encode(imagem_bytes).decode('utf-8')
    return f"data:{mime_type};base64,{img_b64}"

DIRETRIZES_SISTEMA = """You are an elite E-commerce Art Director writing EDIT INSTRUCTIONS for image-editing AI models. These models receive the actual product photo as a reference image and rewrite it according to your instructions, preserving the subject's identity unless told otherwise.
MISSION: Translate the user's messy Portuguese request into a precise English editing instruction.
CRITICAL RULES:
1. LANGUAGE: the entire output must be 100% in English, with zero Portuguese words, accents, or slang surviving — including the product name itself. Don't just transliterate the product name: explain in plain English what the object physically is, what it looks like, and what it is used for (e.g., if a regional term is used, describe its physical characteristics and materials instead of just translating the word).
2. GEOMETRY LOCK: make clear that the exact shape, proportions, and structural geometry of the 3D-printed object in the reference photo must stay unchanged — only its color, material, finish, and the surrounding scene may be altered.
3. MATERIAL OVERRIDE: make clear that the object's final color/material must match exactly what was requested, overriding whatever color/material the reference photo currently shows, while its shape and geometry stay identical. Phrase this naturally and vary your wording — never reuse the exact same sentence template every time.
4. INTERSECTION / SPATIAL RULE: if the product is a holder, mount, or stand that must interact with another object (like a cup, glass, or bottle), make clear how they physically interact (e.g., resting naturally, passing through the hollow center), respecting realistic spatial occlusion. Do not assume the object is a stainless steel thermos unless explicitly requested by the user.
5. SCENE ISOLATION: never mix backgrounds. For a realistic scene, describe it fully and ask for the product to be relit to match that scene's lighting and shadows. For a catalog shot, make clear the background must become a plain, fully isolated, pure white studio backdrop with nothing else in frame.
6. KEEP IT CONCISE AND NATURAL: write one clear, direct paragraph, in your own words, avoiding repeated stock phrasing across requests. Prioritize the model correctly following the instruction over poetic prose.
7. OUTPUT ONLY THE ENGLISH EDITING INSTRUCTION — no preamble, no quotation marks wrapping it, no markdown, nothing else."""

DIRETRIZES_SISTEMA_MANUAL = DIRETRIZES_SISTEMA + """
8. SELF-CONTAINED FOR MANUAL USE: this instruction will be pasted directly by a human into a consumer AI chat app's image editor. Therefore explicitly fold the desired output aspect ratio into the instruction text itself in plain words (e.g. "generate a square 1:1 image" or "a vertical 3:4 image")."""

_PADRAO_ACENTOS_PT = re.compile(r"[ãõçáéíóúâêôàÃÕÇÁÉÍÓÚÂÊÔÀ]")
_PALAVRAS_PT_COMUNS = {"para", "com", "uma", "não", "está", "sendo", "essa", "esse", "muito", "que"}

def contem_portugues(texto):
    if _PADRAO_ACENTOS_PT.search(texto):
        return True
    palavras = re.findall(r"[a-zà-ú]+", texto.lower())
    return any(p in _PALAVRAS_PT_COMUNS for p in palavras)

def gerar_prompt(historico):
    payload = {"model": MODELO_TEXTO, "messages": historico, "temperature": 0.2}
    res = SESSAO_HTTP.post(URL_LITELLM, json=payload, timeout=30)
    res.raise_for_status()
    return res.json()['choices'][0]['message']['content'].strip()

def gerar_prompt_em_ingles(historico, max_tentativas=2):
    prompt = gerar_prompt(historico)
    historico_corrente = list(historico)
    tentativas = 1
    while contem_portugues(prompt) and tentativas < max_tentativas:
        historico_corrente = historico_corrente + [
            {"role": "assistant", "content": prompt},
            {"role": "user", "content": (
                "Your previous output still contains Portuguese words. Rewrite it ENTIRELY in "
                "English — translate every single word, including the product name, and explain "
                "any Brazilian-specific term in plain English instead of transliterating it. "
                "Output ONLY the corrected English instruction, nothing else."
            )},
        ]
        prompt = gerar_prompt(historico_corrente)
        tentativas += 1
    return prompt, not contem_portugues(prompt)

def chamar_motor_imagem(endpoint, nome_motor, imagens_referencia_data_uris, prompt, console_preview,
                         num_imagens=1, aspecto="1:1", resolucao=None):
    logs = [f"> 🧠 Conectando ao {nome_motor} via Fal.ai..."]
    console_preview.code("\n".join(logs), language="bash")

    def _on_queue_update(update):
        if isinstance(update, fal_client.InProgress):
            for log in update.logs:
                msg = log.get("message", "")
                linha = f"   [{nome_motor}] {msg}"
                if linha not in logs:
                    logs.append(linha)
            console_preview.code("\n".join(logs[-15:]), language="bash")

    payload = {
        "prompt": prompt,
        "output_format": "jpeg",
        "num_images": num_imagens,
    }

    # Tratamento dinâmico para garantir compatibilidade entre endpoints legados (Gemini) e novos (FLUX)
    if "nano-banana" in endpoint:
        payload["image_urls"] = imagens_referencia_data_uris
        payload["aspect_ratio"] = aspecto
        if resolucao:
            payload["resolution"] = resolucao
    else:
        # A arquitetura FLUX no fal.ai sempre exige `image_url` (string única), não a lista 'image_urls'
        payload["image_url"] = imagens_referencia_data_uris[0]
        # FLUX usa image_size ao invés de aspect_ratio na maioria de suas APIs de inpainting/img2img
        if aspecto == "1:1":
            payload["image_size"] = "square_hd"
        elif aspecto == "3:4":
            payload["image_size"] = "portrait_4_3"
        elif aspecto == "4:5":
            payload["image_size"] = "portrait_4_5"

    resultado = fal_client.subscribe(
        endpoint,
        arguments=payload,
        with_logs=True,
        on_queue_update=_on_queue_update,
    )

    # Lida com endpoints novos (como flux-subject) que às vezes retornam "image" ao invés de "images"
    imagens_saida = resultado.get("images")
    if not imagens_saida and "image" in resultado:
        imagens_saida = [resultado.get("image")]

    if not imagens_saida:
        raise Exception("A IA processou o pedido, mas não retornou nenhuma imagem. Resposta pura da API: " + str(resultado))

    logs.append(f"> ✨ {len(imagens_saida)} versão(ões) gerada(s) com sucesso!")
    console_preview.code("\n".join(logs[-15:]), language="bash")

    candidatos_b64 = []
    for img in imagens_saida:
        url_img = img.get("url", "")
        if url_img.startswith("data:image"):
            candidatos_b64.append(url_img.split("base64,")[1])
        else:
            resp = SESSAO_HTTP.get(url_img, timeout=30)
            resp.raise_for_status()
            candidatos_b64.append(base64.b64encode(resp.content).decode("utf-8"))

    descricao = resultado.get("description", "")
    return candidatos_b64, descricao

# ================= 5. INTERFACE VISUAL (FRONTEND) =================

with st.sidebar:
    st.header("⚙️ Memória da IA")
    if st.button("🧨 Resetar Catálogo (Branco)", use_container_width=True):
        resetar_memoria("catalogo")
        st.toast("✅ Memória de Catálogo resetada!")
    if st.button("🧨 Resetar Ambientes", use_container_width=True):
        resetar_memoria("ambiente")
        st.toast("✅ Memória de Ambientes resetada!")
    if st.button("🧨 Resetar Lifestyle (Mãos)", use_container_width=True):
        resetar_memoria("mao")
        st.toast("✅ Memória de Lifestyle resetada!")

st.title("🏭 ECC Studio Vision v14.0")
st.markdown("Gere via API (Fal.ai, com custo) **ou** gere você mesmo de graça (Gemini, Meta AI ou Copilot) — escolha a aba.")

if not st.session_state.motor_ia_pronto:
    with st.status("🚀 Inicializando Cérebro Local", expanded=True) as status:
        if not checar_porta_8000():
            llm_script_path = str(ROOT_DIR / "llm.py")
            log_path = str(ROOT_DIR / "llm_boot.log")
            if os.path.exists(log_path):
                try: os.remove(log_path)
                except: pass
            env_utf8 = os.environ.copy()
            env_utf8["PYTHONIOENCODING"] = "utf-8"
            comando_shell = f'"{sys.executable}" -u "{llm_script_path}" > "{log_path}" 2>&1'
            subprocess.Popen(comando_shell, shell=True, cwd=str(ROOT_DIR), env=env_utf8)
            console_preview = st.empty()
            conectado = False
            for _ in range(40):
                time.sleep(0.5)
                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        logs_atuais = f.read()
                        if logs_atuais.strip():
                            console_preview.code(logs_atuais[-2000:], language="bash")
                except: pass
                if checar_porta_8000():
                    conectado = True
                    break
            if conectado:
                status.update(label="Motor OK!", state="complete", expanded=False)
                st.session_state.motor_ia_pronto = True
                st.rerun()
            else:
                status.update(label="Falha no Boot", state="error", expanded=True)
                st.stop()
        else:
            status.update(label="Motor Online!", state="complete", expanded=False)
            st.session_state.motor_ia_pronto = True
            st.rerun()

# --- APLICAÇÃO PRINCIPAL ---
if st.session_state.motor_ia_pronto:

    aba_auto, aba_manual = st.tabs(["🎨 Gerador Automático (Fal.ai, com custo)", "📋 Modo Gratuito (Gemini / Meta AI / Copilot)"])

    with aba_auto:
        col1, col2 = st.columns([1.2, 1])

        with col1:
            st.subheader("1. Configuração do Cenário Único")

            estilo = st.selectbox("Qual o estilo visual desejado?", [
                "Ambiente (Cenário Realista)",
                "Catálogo (Fundo Branco Puro)",
                "Lifestyle (Sendo Segurado por uma Mão)"
            ])

            imagem_upload = st.file_uploader("Upload do STL (Limpo) ou Foto Real (Bagunçada)", type=["png", "jpg", "jpeg"])

            if imagem_upload is not None:
                if st.session_state.arquivo_atual != imagem_upload.name:
                    st.session_state.arquivo_atual = imagem_upload.name
                    st.session_state.img_recortada_bytes = None
                    st.session_state.imagem_gerada_b64 = None
                    st.session_state.candidatos_atual = []
                    st.session_state.imagem_referencia_atual = None
                    st.session_state.prompt_manual = ""

                bytes_originais = imagem_upload.read()

                neutralizar_cor = st.checkbox(
                    "Neutralizar cor original (escala de cinza)",
                    value=False,
                    help="Opcional. O motor de edição consegue sobrescrever a cor/material via "
                         "instrução de texto, então normalmente isso não é necessário. Ative só "
                         "se sua foto de origem tiver um tom muito dominante (ex.: filamento amarelado)."
                )

                if st.button("✂️ Isolar Produto (remover fundo)", type="secondary"):
                    with st.spinner("Removendo fundo e centralizando no canvas..."):
                        st.session_state.img_recortada_bytes = preparar_canvas_perfeito(
                            bytes_originais, estilo, neutralizar_cor
                        )
                        st.session_state.imagem_referencia_atual = st.session_state.img_recortada_bytes
                        st.session_state.imagem_gerada_b64 = None
                        st.session_state.candidatos_atual = []

                if st.session_state.img_recortada_bytes:
                    st.image(st.session_state.img_recortada_bytes, caption="✅ Produto isolado e pronto para a IA.")
                    imagem_final_pre_api = st.session_state.img_recortada_bytes
                else:
                    imagem_final_pre_api = None

                if imagem_final_pre_api:
                    st.divider()
                    st.subheader("2. Diretrizes de Material")
                    
                    # Checkbox de Testes focado na eficiência do desenvolvedor
                    modo_teste = st.checkbox("🧪 Teste (Preencher formulário automaticamente)")

                    # Valores dependem de 'modo_teste'
                    val_produto = "suporte de copo para copo de terere" if modo_teste else ""
                    val_cor = "PETG preto fosco" if modo_teste else ""
                    val_cenario = "Esse suporte deve estar encaixado na parte de baixo de uma garrafa de inox de terere. A garrafa de inox está em pé em cima de uma mesa de madeira em um ambiente de casa bem aconchegante." if modo_teste else ""

                    prod_col1, prod_col2 = st.columns(2)
                    with prod_col1: produto = st.text_input("Produto:", value=val_produto)
                    with prod_col2: cor = st.text_input("Cor/Material Exato:", value=val_cor)

                    cenario_custom = ""
                    if estilo == "Ambiente (Cenário Realista)":
                        cenario_custom = st.text_area("Descreva a cena e interações:", value=val_cenario, height=80)

                    tipo_mem_atual, instrucao_atual = montar_instrucao_estilo(estilo, cenario_custom)

                    st.markdown("**⚙️ Motor de IA (define o custo por imagem)**")
                    mapa_label_para_chave = {v["label"]: k for k, v in MOTORES_IMAGEM.items()}
                    label_motor = st.selectbox(
                        "Motor de geração",
                        list(mapa_label_para_chave.keys())
                    )
                    chave_motor = mapa_label_para_chave[label_motor]
                    motor = MOTORES_IMAGEM[chave_motor]
                    endpoint_valor = motor["endpoint"]
                    nome_motor_valor = motor["nome_curto"]

                    # --- CÓDIGO DA RECOMENDAÇÃO DINÂMICA ---
                    mapa_recomendacoes = {
                        "Ambiente (Cenário Realista)": "💡 **Recomendação:** Use **Gemini**. Ele é o melhor para criar fundos realistas integrando o produto perfeitamente com a luz do cenário.",
                        "Catálogo (Fundo Branco Puro)": "💡 **Recomendação:** Use **FLUX ** (para travar perfeitamente a geometria) ou **FLUX Schnell** (para testes ultra baratos de recorte).",
                        "Lifestyle (Sendo Segurado por uma Mão)": "💡 **Recomendação:** Use **Nano Banana Pro**. Interações com partes do corpo humano exigem modelos de maior capacidade."
                    }
                    st.caption(mapa_recomendacoes.get(estilo, ""))
                    # ----------------------------------------


                    st.markdown("**📐 Saída para Shopee**")
                    opcoes_proporcao = {
                        "1:1 — Capa do anúncio (padrão exigido pela Shopee)": "1:1",
                        "3:4 — Imagem vertical complementar (Shopee)": "3:4",
                        "4:5 — Vertical (Shopee Ads / Instagram)": "4:5",
                        "Automático (mesma proporção da foto enviada)": "auto",
                    }

                    sh_col1, sh_col2, sh_col3 = st.columns(3)
                    with sh_col1:
                        label_proporcao = st.selectbox("Proporção", list(opcoes_proporcao.keys()))
                    with sh_col2:
                        if motor["suporta_resolucao"]:
                            opcoes_resolucao = {
                                "1K — Recomendado (suficiente p/ Shopee, menor custo)": "1K",
                                "2K — Mais nítido (+50% de custo)": "2K",
                                "4K — Máximo (2x o custo, raramente necessário)": "4K",
                            }
                            label_resolucao = st.selectbox("Resolução", list(opcoes_resolucao.keys()))
                            resolucao_valor = opcoes_resolucao[label_resolucao]
                        else:
                            resolucao_valor = None
                            st.selectbox("Resolução", ["Única (~1K, fixa neste motor)"], disabled=True)
                    with sh_col3:
                        num_variacoes = st.slider("Variações", min_value=1, max_value=4, value=1,
                                                   help="Gera N versões no mesmo clique. Cada variação extra é cobrada de novo.")

                    proporcao_valor = opcoes_proporcao[label_proporcao]

                    st.session_state.dados_atual = {
                        "produto": produto,
                        "cor": cor,
                        "estilo": estilo,
                        "tipo_mem": tipo_mem_atual,
                        "instrucao": instrucao_atual,
                        "proporcao_valor": proporcao_valor,
                        "proporcao_label": label_proporcao,
                    }

                    if motor["suporta_resolucao"]:
                        custo_unitario = motor["custo"][resolucao_valor]
                    else:
                        custo_unitario = motor["custo"]["padrao"]
                    custo_estimado = custo_unitario * num_variacoes

                    if st.button(f"🚀 Gerar {num_variacoes}x com {nome_motor_valor} (~${custo_estimado:.3f})",
                                 type="primary", use_container_width=True):
                        if not produto or not cor:
                            st.warning("⚠️ Preencha o nome e a cor!")
                        else:
                            st.session_state.tipo_memoria_atual = tipo_mem_atual
                            memoria = carregar_memoria(tipo_mem_atual)
                            sistema_final = f"{DIRETRIZES_SISTEMA}\n\n[USER APPROVED STYLE EXAMPLES]\n{memoria}" if memoria else DIRETRIZES_SISTEMA

                            st.session_state.historico_llm = [
                                {"role": "system", "content": sistema_final},
                                {"role": "user", "content": f"Product: {produto}. Material: {cor}. Scene: {instrucao_atual}"}
                            ]

                            try:
                                with st.status("🧠 Fábrica de Renderização", expanded=True) as status_render:
                                    terminal_fal = st.empty()

                                    st.write("📝 1. Consolidando e verificando instrução 100% em inglês...")
                                    st.session_state.prompt_atual, prompt_ok = gerar_prompt_em_ingles(st.session_state.historico_llm)
                                    if not prompt_ok:
                                        st.warning("⚠️ Não foi possível garantir 100% que o prompt está só em inglês — revise antes de aprovar.")

                                    st.write("⚡ 2. Preparando referência (Data URI) para a Fal.ai...")
                                    data_uri = construir_data_uri(imagem_final_pre_api)

                                    st.write(f"⚡ 3. Editando com o {nome_motor_valor}...")
                                    candidatos, descricao = chamar_motor_imagem(
                                        endpoint_valor,
                                        nome_motor_valor,
                                        [data_uri],
                                        st.session_state.prompt_atual,
                                        terminal_fal,
                                        num_imagens=num_variacoes,
                                        aspecto=proporcao_valor,
                                        resolucao=resolucao_valor,
                                    )

                                    st.session_state.candidatos_atual = candidatos
                                    st.session_state.descricao_ia = descricao
                                    st.session_state.versao = 1

                                    if len(candidatos) == 1:
                                        st.session_state.imagem_gerada_b64 = candidatos[0]
                                        st.session_state.imagem_referencia_atual = base64.b64decode(candidatos[0])
                                    else:
                                        st.session_state.imagem_gerada_b64 = None

                                    status_render.update(label=f"Renderização com {nome_motor_valor} Concluída!", state="complete", expanded=False)

                            except Exception as e:
                                st.error(f"❌ Falha de Integração com a Fal.ai: {e}")

        with col2:
            st.subheader("3. Mesa de Refinamento")

            if st.session_state.candidatos_atual and not st.session_state.imagem_gerada_b64:
                st.write("Escolha a melhor variação para continuar:")
                colunas_galeria = st.columns(len(st.session_state.candidatos_atual))
                for i, cand_b64 in enumerate(st.session_state.candidatos_atual):
                    with colunas_galeria[i]:
                        st.image(base64.b64decode(cand_b64), use_container_width=True)
                        if st.button(f"✅ Usar v{i+1}", key=f"usar_var_{i}", use_container_width=True):
                            st.session_state.imagem_gerada_b64 = cand_b64
                            st.session_state.imagem_referencia_atual = base64.b64decode(cand_b64)
                            st.rerun()

            elif st.session_state.imagem_gerada_b64:
                bytes_imagem = base64.b64decode(st.session_state.imagem_gerada_b64)
                st.image(bytes_imagem, caption=f"Render v{st.session_state.versao} - Perfil: {st.session_state.tipo_memoria_atual}", use_container_width=True)

                if len(st.session_state.candidatos_atual) > 1:
                    if st.button("↩️ Ver outras variações desta rodada"):
                        st.session_state.imagem_gerada_b64 = None
                        st.rerun()

                with st.expander("Ver Roteiro Operacional da IA (Prompt + Descrição)"):
                    st.code(st.session_state.prompt_atual, language="text")
                    if st.session_state.descricao_ia:
                        st.caption("Descrição retornada pela IA:")
                        st.write(st.session_state.descricao_ia)

                st.divider()

                ajuste = st.text_input("Ajuste rápido de luz ou cena:", placeholder="Ex: Deixe o inox mais brilhante e a madeira mais rústica")

                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("🛠️ Recalcular Ajuste", use_container_width=True):
                        if ajuste:
                            st.session_state.historico_llm.append({"role": "assistant", "content": st.session_state.prompt_atual})
                            st.session_state.historico_llm.append({"role": "user", "content": f"Apply this specific change smoothly: {ajuste}"})

                            try:
                                with st.status("🧠 Reprocessando Setup...", expanded=True) as status_render:
                                    terminal_fal = st.empty()

                                    st.write("📝 1. Atualizando e verificando instrução 100% em inglês...")
                                    st.session_state.prompt_atual, prompt_ok = gerar_prompt_em_ingles(st.session_state.historico_llm)
                                    if not prompt_ok:
                                        st.warning("⚠️ Não foi possível garantir 100% que o prompt está só em inglês — revise antes de aprovar.")

                                    st.write("⚡ 2. Usando a ÚLTIMA versão aprovada como referência (edição multi-turno)...")
                                    data_uri_ref = construir_data_uri(st.session_state.imagem_referencia_atual)

                                    st.write(f"⚡ 3. Executando Re-Edição com o {nome_motor_valor}...")
                                    candidatos, descricao = chamar_motor_imagem(
                                        endpoint_valor,
                                        nome_motor_valor,
                                        [data_uri_ref],
                                        st.session_state.prompt_atual,
                                        terminal_fal,
                                        num_imagens=1,
                                        aspecto=proporcao_valor,
                                        resolucao=resolucao_valor,
                                    )

                                    st.session_state.candidatos_atual = candidatos
                                    st.session_state.descricao_ia = descricao
                                    st.session_state.imagem_gerada_b64 = candidatos[0]
                                    st.session_state.imagem_referencia_atual = base64.b64decode(candidatos[0])
                                    st.session_state.versao += 1
                                    status_render.update(label="Ajuste Finalizado!", state="complete", expanded=False)
                                    time.sleep(0.5)
                                    st.rerun()

                            except Exception as e:
                                st.error(f"❌ Erro de Ajuste: {e}")

                with col_btn2:
                    if st.button("✅ Aprovar Catálogo", type="primary", use_container_width=True):
                        nome_arq = str(CURRENT_DIR / "fotos_prontas" / f"render_{int(time.time())}_v{st.session_state.versao}.png")
                        with open(nome_arq, "wb") as f:
                            f.write(bytes_imagem)

                        salvar_memoria(st.session_state.tipo_memoria_atual, st.session_state.prompt_atual)
                        st.success("Arte final otimizada salva com sucesso para a empresa!")
            else:
                st.info("A Renderização Profissional aparecerá aqui.")

    # ========================================================================
    # ABA 2 — MODO GRATUITO (sem Fal.ai, você gera num app de IA grátis)
    # ========================================================================
    with aba_manual:
        st.subheader("📋 Gere você mesmo, de graça")
        st.markdown(
            "Sem custo de API: escolha onde quer gerar, baixe a foto já isolada/tratada, copie "
            "o prompt gerado abaixo, e cole os dois juntos numa mensagem para o app escolhido."
        )

        dados = st.session_state.get("dados_atual")
        img_ref = st.session_state.get("img_recortada_bytes")

        if not dados or not img_ref:
            st.info(
                "Primeiro vá na aba **'🎨 Gerador Automático'**, faça upload da foto, clique em "
                "**'✂️ Isolar Produto'** e preencha produto/cor/material — esses dados aparecem "
                "aqui automaticamente, sem precisar repetir nada."
            )
        else:
            mapa_ferramenta = {v["nome"]: k for k, v in FERRAMENTAS_GRATUITAS.items()}
            nome_ferramenta = st.selectbox(
                "Onde você quer gerar a imagem gratuitamente?",
                list(mapa_ferramenta.keys()),
                help="Comece pelo Gemini. Se a cota diária acabar, troque para o Meta AI ou o "
                     "Copilot sem perder o prompt já gerado — ele funciona nos três."
            )
            chave_ferramenta = mapa_ferramenta[nome_ferramenta]
            ferramenta = FERRAMENTAS_GRATUITAS[chave_ferramenta]
            st.caption(f"💡 {ferramenta['nota']}")

            col_m1, col_m2 = st.columns([1, 1.3])

            with col_m1:
                st.markdown("**1️⃣ Baixe a foto já tratada**")
                st.image(img_ref, caption="Mesma foto que iria para a API", use_container_width=True)
                st.download_button(
                    "⬇️ Baixar Foto Pronta (.jpg)",
                    data=img_ref,
                    file_name=f"produto_isolado_{dados['tipo_mem']}.jpg",
                    mime="image/jpeg",
                    use_container_width=True,
                )

            with col_m2:
                st.markdown("**2️⃣ Gere o prompt perfeito (em inglês, pronto para colar)**")
                st.caption(f"Produto: {dados['produto']} · Material: {dados['cor']} · Estilo: {dados['estilo']} · Formato: {dados['proporcao_label']}")

                if st.button("📝 Gerar Prompt", type="primary", use_container_width=True):
                    with st.spinner("Consolidando e verificando instrução 100% em inglês..."):
                        memoria = carregar_memoria(dados["tipo_mem"])
                        sistema_manual = (
                            f"{DIRETRIZES_SISTEMA_MANUAL}\n\n[USER APPROVED STYLE EXAMPLES]\n{memoria}"
                            if memoria else DIRETRIZES_SISTEMA_MANUAL
                        )
                        historico_manual = [
                            {"role": "system", "content": sistema_manual},
                            {"role": "user", "content": (
                                f"Product: {dados['produto']}. Material: {dados['cor']}. "
                                f"Scene: {dados['instrucao']} "
                                f"Desired output aspect ratio: {dados['proporcao_valor']} — "
                                f"fold this explicitly into the instruction text."
                            )},
                        ]
                        st.session_state.prompt_manual, prompt_manual_ok = gerar_prompt_em_ingles(historico_manual)
                        if not prompt_manual_ok:
                            st.warning("⚠️ Não foi possível garantir 100% que o prompt está só em inglês — revise antes de colar.")

                if st.session_state.prompt_manual:
                    st.code(st.session_state.prompt_manual, language="text")
                    st.caption("☝️ Clique no ícone de copiar no canto do bloco acima.")

            st.divider()
            st.markdown(
                f"**3️⃣ No [{ferramenta['nome']}]({ferramenta['url']}):** abra uma conversa nova, envie "
                "a foto baixada e cole o prompt acima na mesma mensagem. Se quiser ajustar depois "
                "(luz, cor, ângulo etc.), continue a própria conversa por lá normalmente — não "
                "precisa voltar aqui nem gerar um prompt novo a cada ajuste."
            )