import contextlib
import os
import secrets
import threading
import time
import hmac
import hashlib
import requests
from dotenv import load_dotenv, set_key
from loguru import logger
from pathlib import Path

# Carrega chaves da raiz
ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / "CHAVES_DADOS.env"
load_dotenv(ENV_FILE)

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", 0))
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").encode('utf-8')
SHOP_ID = int(os.getenv("SHOPEE_SHOP_ID", 0))
BASE_URL = "https://partner.shopeemobile.com"

# ==============================================================================
# MOTOR DE AUTENTICAÇÃO INTELIGENTE (Auto-Renovação de Token)
#
# O refresh_token da Shopee é de USO ÚNICO: se dois processos (app + um worker
# via CLI, ou o app aberto duas vezes) renovarem com o mesmo token, a cadeia é
# invalidada e a integração morre até rodar pegar_token.py de novo. Por isso a
# renovação é protegida por um lock de arquivo (entre processos) + lock de
# thread (dentro do processo), e o .env é RELIDO já dentro do lock — se outro
# processo renovou enquanto esperávamos, usamos o token novo dele.
# ==============================================================================
_CACHE_ACCESS_TOKEN = None
_CACHE_EXPIRATION = 0
_TOKEN_THREAD_LOCK = threading.Lock()
_TOKEN_LOCK_FILE = ROOT_DIR / ".shopee_token.lock"


@contextlib.contextmanager
def _trava_renovacao_entre_processos():
    """Lock exclusivo de arquivo, cross-platform. Se o mecanismo de lock do SO
    falhar, segue sem ele (app single-user: melhor renovar do que travar)."""
    handle = None
    travado = False
    try:
        handle = open(_TOKEN_LOCK_FILE, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX)
            travado = True
        except Exception as exc:
            logger.warning(f"Lock de renovação de token indisponível; seguindo sem ele: {exc}")
        yield
    finally:
        if handle is not None:
            if travado:
                try:
                    if os.name == "nt":
                        import msvcrt
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle, fcntl.LOCK_UN)
                except Exception:
                    pass
            handle.close()


def obter_access_token():
    """Gera e renova o access_token de forma autônoma usando o refresh_token."""
    global _CACHE_ACCESS_TOKEN, _CACHE_EXPIRATION

    # Fora do lock: caminho quente (token válido em memória)
    if _CACHE_ACCESS_TOKEN and time.time() < _CACHE_EXPIRATION:
        return _CACHE_ACCESS_TOKEN

    with _TOKEN_THREAD_LOCK:
        # Outra thread pode ter renovado enquanto esperávamos o lock
        if _CACHE_ACCESS_TOKEN and time.time() < _CACHE_EXPIRATION:
            return _CACHE_ACCESS_TOKEN

        with _trava_renovacao_entre_processos():
            # Outro PROCESSO pode ter renovado: relê o .env para pegar o
            # refresh_token mais novo antes de gastar o nosso (uso único!).
            load_dotenv(ENV_FILE, override=True)
            refresh_token = os.getenv("SHOPEE_REFRESH_TOKEN", "")

            if not refresh_token:
                logger.error("Refresh Token não encontrado no CHAVES_DADOS.env")
                return None

            path = "/api/v2/auth/access_token/get"
            timestamp = int(time.time())
            base_string = f"{PARTNER_ID}{path}{timestamp}".encode('utf-8')
            sign = hmac.new(PARTNER_KEY, base_string, hashlib.sha256).hexdigest()

            url = f"{BASE_URL}{path}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
            payload = {
                "refresh_token": refresh_token,
                "partner_id": PARTNER_ID,
                "shop_id": SHOP_ID
            }

            try:
                res = requests.post(url, json=payload, timeout=20).json()

                if res.get("error"):
                    logger.error(f"Falha ao gerar Token na Shopee: {res.get('message')}")
                    return None

                _CACHE_ACCESS_TOKEN = res.get("access_token")
                novo_refresh = res.get("refresh_token")

                # O Access Token dura 4 horas. Vamos forçar a renovação a cada 3 horas por segurança.
                _CACHE_EXPIRATION = time.time() + 10800

                # Salva o novo refresh_token no .env para o sistema nunca mais quebrar!
                set_key(str(ENV_FILE), "SHOPEE_REFRESH_TOKEN", novo_refresh)
                os.environ["SHOPEE_REFRESH_TOKEN"] = novo_refresh

                logger.success("🔑 Conexão validada! Access Token gerado com sucesso.")
                return _CACHE_ACCESS_TOKEN
            except Exception as e:
                logger.error(f"Erro ao comunicar com a API de Autenticação: {e}")
                return None

def gerar_assinatura(path, access_token):
    """Gera a assinatura criptografada obrigatória da Shopee v2."""
    timestamp = int(time.time())
    base_string = f"{PARTNER_ID}{path}{timestamp}{access_token}{SHOP_ID}".encode('utf-8')
    sign = hmac.new(PARTNER_KEY, base_string, hashlib.sha256).hexdigest()
    return timestamp, sign

# ==============================================================================
# COMUNICADOR CENTRAL
# ==============================================================================

# Sessão compartilhada: reaproveita a conexão TLS entre as centenas de chamadas
# sequenciais de um backfill (escrow chama a API 1 vez por pedido).
_HTTP_SESSION = requests.Session()


def _espera_retry(response, tentativa):
    """Backoff exponencial limitado, respeitando o Retry-After quando enviado."""
    try:
        sugerido = int(response.headers.get("Retry-After", "") or 0)
    except (TypeError, ValueError):
        sugerido = 0
    return min(15, max(sugerido, 2 ** tentativa))


def chamar_shopee_api(path, params=None, method="GET", payload=None, max_tentativas=3):
    """
    Motor centralizado de chamadas para a Shopee API v2, com retry disciplinado:

      - GET (leitura) é idempotente: repete em 429, 5xx, timeout e falha de rede.
      - POST (atuação: preço/promoção/combo) só repete em 429 — nunca após
        timeout ou 5xx, para não aplicar a mesma ação duas vezes na loja.

    A assinatura é regenerada a cada tentativa: o timestamp faz parte dela e
    uma retentativa com assinatura velha seria rejeitada.
    """
    metodo = method.upper()
    if metodo not in {"GET", "POST"}:
        logger.error(f"Método HTTP não suportado: {method}")
        return None

    url = f"{BASE_URL}{path}"

    for tentativa in range(1, max_tentativas + 1):
        access_token = obter_access_token()
        if not access_token:
            return None

        timestamp, sign = gerar_assinatura(path, access_token)
        params_completos = dict(params or {})
        params_completos.update({
            "partner_id": PARTNER_ID,
            "timestamp": timestamp,
            "access_token": access_token,
            "shop_id": SHOP_ID,
            "sign": sign
        })

        try:
            if metodo == "GET":
                response = _HTTP_SESSION.get(url, params=params_completos, timeout=(10, 30))
            else:
                response = _HTTP_SESSION.post(url, params=params_completos, json=payload, timeout=(10, 30))
        except requests.exceptions.RequestException as e:
            if metodo == "GET" and tentativa < max_tentativas:
                espera = min(8, 2 ** tentativa)
                logger.warning(f"Falha de rede em {path} (tentativa {tentativa}/{max_tentativas}); nova tentativa em {espera}s: {e}")
                time.sleep(espera)
                continue
            logger.error(f"Falha de Rede ao tentar {metodo} em {path}: {e}")
            return None

        # 🤫 SILENCIADOR DE MÓDULOS OPCIONAIS — Insight, Ads e Account Health
        # dependem de permissão marcada no console da Open Platform (apps
        # "seller in-house" precisam habilitar módulo a módulo; 403/404 = não
        # habilitado). A ausência vira None e a UI explica como habilitar,
        # em vez de poluir o log com erro. Flagrado em teste real: account_
        # health respondeu 403 Forbidden nesta conta.
        _MODULOS_OPCIONAIS = ("/api/v2/insight", "/api/v2/ads", "/api/v2/account_health")
        if response.status_code in (403, 404) and any(m in path for m in _MODULOS_OPCIONAIS):
            logger.warning(f"Módulo opcional sem permissão para este app ({response.status_code}): {path}")
            return None

        # 429 é seguro repetir sempre (a Shopee não processou); 5xx só em GET.
        deve_repetir = response.status_code == 429 or (response.status_code >= 500 and metodo == "GET")
        if deve_repetir and tentativa < max_tentativas:
            espera = _espera_retry(response, tentativa)
            logger.warning(f"Shopee respondeu {response.status_code} em {path} (tentativa {tentativa}/{max_tentativas}); aguardando {espera}s.")
            time.sleep(espera)
            continue

        try:
            response.raise_for_status()
            data = response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            logger.error(f"Resposta inválida da Shopee em {metodo} {path}: {e}")
            return None

        if data.get("error"):
            logger.error(f"Shopee API Erro ({path}): {data.get('error')} - {data.get('message')}")
            return None

        return data.get("response", {})

    return None
    
# ==============================================================================
# FUNÇÕES ATUADORAS (Usadas pelo Cérebro IA para manipular a loja)
# ==============================================================================

def atualizar_preco_shopee(item_id, model_id, novo_preco):
    """Altera definitivamente o preço de uma variação."""
    path = "/api/v2/product/update_price"
    
    payload = {
        "item_id": item_id,
        "price_list": [
            {
                "model_id": model_id,
                "original_price": float(novo_preco)
            }
        ]
    }
    
    logger.info(f"Enviando ordem para Shopee: Item {item_id}, Novo Preço: {novo_preco}")
    resposta = chamar_shopee_api(path, method="POST", payload=payload)
    
    if resposta is not None:
        falhas = resposta.get("failure_list", [])
        if falhas:
            logger.error(f"A Shopee rejeitou a alteração: {falhas}")
            return False, str(falhas)
        return True, "Sucesso"
        
    return False, "Falha de Comunicação com a Shopee."

def criar_promocao_shopee(item_id, model_id, preco_promocional, horas_duracao=24):
    path_add_discount = "/api/v2/discount/add_discount"
    path_add_item = "/api/v2/discount/add_discount_item"

    start_time = int(time.time()) + 1800
    end_time = start_time + (int(horas_duracao) * 3600)
    nome_promocao = f"Flash_IA_{int(time.time())}"

    payload_discount = {
        "discount_name": nome_promocao,
        "start_time": start_time,
        "end_time": end_time
    }

    logger.info(f"Criando Campanha de Desconto: {nome_promocao}")
    resp_campanha = chamar_shopee_api(path_add_discount, method="POST", payload=payload_discount)

    if not resp_campanha or "discount_id" not in resp_campanha:
        msg_erro = resp_campanha.get('warning', 'Erro desconhecido') if resp_campanha else 'Sem resposta'
        return False, f"Falha ao criar campanha base: {msg_erro}"

    discount_id = resp_campanha["discount_id"]

    payload_item = {
        "discount_id": discount_id,
        "item_list": [
            {
                "item_id": item_id,
                "model_list": [
                    {
                        "model_id": model_id,
                        "model_promotion_price": float(preco_promocional),
                        "model_promotion_stock": 0
                    }
                ]
            }
        ]
    }

    resp_item = chamar_shopee_api(path_add_item, method="POST", payload=payload_item)

    # LOG CRU — essencial para descobrir o formato real que sua conta recebe
    logger.debug(f"Resposta bruta add_discount_item: {resp_item}")

    if resp_item is None:
        return False, "Falha de comunicação ao vincular item à campanha."

    # A Shopee costuma retornar falhas item-a-item aninhadas, não no campo 'error' de topo.
    # Verificamos todos os nomes de campo plausíveis, já que o formato varia por versão/região.
    falhas = (
        resp_item.get("failed_list")
        or resp_item.get("failed_items")
        or resp_item.get("warning")
        or []
    )
    if falhas:
        logger.error(f"Shopee rejeitou o item na campanha: {falhas}")
        return False, f"Item rejeitado: {falhas}"

    return True, discount_id  # devolvemos o discount_id, não só uma mensagem — precisamos dele pra verificar depois

def verificar_status_promocao(discount_id):
    """
    Consulta o estado real da campanha na Shopee.
    Retorna: ('upcoming' | 'ongoing' | 'expired' | 'rejeitado' | 'desconhecido', detalhe)
    """
    path = "/api/v2/discount/get_discount"
    params = {"discount_id": discount_id}

    resp = chamar_shopee_api(path, params=params, method="GET")
    logger.debug(f"Resposta bruta get_discount: {resp}")

    if resp is None:
        return "desconhecido", "Sem resposta da Shopee ao consultar status."

    status = resp.get("status", "desconhecido")
    itens = resp.get("item_list", [])

    # Confere se o item de fato está presente e ativo dentro da campanha
    item_encontrado = any(
        i.get("item_id") for i in itens
    ) if itens else False

    if not item_encontrado:
        return "rejeitado", "Campanha existe, mas nenhum item está vinculado a ela."

    return status, f"{len(itens)} item(ns) vinculado(s) à campanha."

def criar_combo_shopee(item_id, percentual_desconto=10, limite_compras=100):
    """
    Cria um 'Bundle Deal' (Leve 2, Pague menos) para diluir frete e aumentar conversão.
    (Integração bônus para habilitar o comando 'CRIAR_COMBO' da IA).

    Retorna (True, bundle_deal_id) — o ID numérico, e não uma mensagem, para o
    chamador poder registrar/verificar o combo depois — ou (False, motivo).
    """
    path_add_bundle = "/api/v2/bundle_deal/add_bundle_deal"
    path_add_item = "/api/v2/bundle_deal/add_bundle_deal_item"
    
    start_time = int(time.time()) + 1800 
    end_time = start_time + (7 * 24 * 3600) # Dura 7 dias por padrão
    nome_combo = f"Combo_IA_{int(time.time())}"
    
    # Bundle type 2 = "Percentage Discount" (Ex: Compre 2 e ganhe 10% off)
    payload_bundle = {
        "bundle_deal_name": nome_combo,
        "start_time": start_time,
        "end_time": end_time,
        "bundle_deal_rule_type": 2, 
        "rule_info": {
            "min_amount": 2, # Compre 2 unidades
            "discount_percentage": int(percentual_desconto) # Ganhe X% de desconto
        },
        "purchase_limit": limite_compras
    }
    
    resp_bundle = chamar_shopee_api(path_add_bundle, method="POST", payload=payload_bundle)
    
    if not resp_bundle or "bundle_deal_id" not in resp_bundle:
        return False, "Falha ao criar regra do Combo Base."
        
    bundle_id = resp_bundle["bundle_deal_id"]
    
    # Vincula o item ao Combo
    payload_item = {
        "bundle_deal_id": bundle_id,
        "item_list": [{"item_id": item_id, "status": 1}]
    }
    
    resp_item = chamar_shopee_api(path_add_item, method="POST", payload=payload_item)

    if resp_item is None:
        return False, "Falha ao atrelar item ao Combo."

    # A Shopee devolve rejeições item-a-item aninhadas (não no 'error' de topo);
    # o nome do campo varia por versão/região — mesmo tratamento da promoção.
    falhas = resp_item.get("failed_list") or resp_item.get("failure_list") or []
    if falhas:
        logger.error(f"Shopee rejeitou o item no combo: {falhas}")
        return False, f"Item rejeitado no combo: {falhas}"

    return True, bundle_id


# ==============================================================================
# SAÚDE DA CONTA (v2.account_health) — o que decide o ALCANCE orgânico da loja
# ==============================================================================

def obter_saude_conta():
    """Lê a saúde operacional da loja direto da API oficial.

    Nomes de endpoint VALIDADOS AO VIVO nesta conta (14/07/2026): a família
    atual usa o prefixo get_ ('get_shop_performance'); os nomes antigos sem
    get_ respondem 403 e NÃO significam falta de permissão do app.

    Retorna dict com performance, pontos de penalidade, punições ativas,
    anúncios com problema e pedidos atrasados — ou None se o módulo estiver
    realmente indisponível.
    """
    performance = chamar_shopee_api("/api/v2/account_health/get_shop_performance")
    if performance is None:
        return None
    return {
        "performance": performance,
        "pontos": chamar_shopee_api("/api/v2/account_health/get_penalty_point_history") or {},
        "punicoes_ativas": chamar_shopee_api(
            "/api/v2/account_health/get_punishment_history", params={"punishment_status": 1}) or {},
        "listagens_com_problema": chamar_shopee_api(
            "/api/v2/account_health/get_listings_with_issues", params={"page_no": 1, "page_size": 100}) or {},
        "pedidos_atrasados": chamar_shopee_api(
            "/api/v2/account_health/get_late_orders", params={"page_no": 1, "page_size": 100}) or {},
    }


# ==============================================================================
# BOOST DE PRODUTOS (v2.product.boost_item) — alcance GRÁTIS, 5 itens / 4 horas
# ==============================================================================

def listar_boost_ativo():
    """IDs dos itens atualmente impulsionados (a Shopee permite até 5 por vez;
    cada boost dura 4 horas). Retorna lista de item_ids ou None em falha."""
    resp = chamar_shopee_api("/api/v2/product/get_boosted_list")
    if resp is None:
        return None
    lista = resp.get("item_id_list") or []
    # Algumas regiões devolvem [{"item_id": ...}] em vez de [int]
    return [i.get("item_id", i) if isinstance(i, dict) else int(i) for i in lista]


def impulsionar_itens(item_ids):
    """Impulsiona até 5 itens (aparecem primeiro na aba da loja e ganham
    prioridade nas recomendações por 4 horas — recurso gratuito da Shopee).

    Retorna (lista_sucesso, lista_falhas[(item_id, motivo)]).
    """
    payload = {"item_id_list": [int(i) for i in item_ids[:5]]}
    logger.info(f"Boost solicitado para itens: {payload['item_id_list']}")
    resp = chamar_shopee_api("/api/v2/product/boost_item", method="POST", payload=payload)
    if resp is None:
        return [], [(i, "Sem resposta da Shopee") for i in payload["item_id_list"]]

    falhas = [
        (f.get("item_id"), f.get("failed_reason", "motivo não informado"))
        for f in (resp.get("failure_list") or [])
    ]
    sucesso = list(resp.get("success_list") or [])
    if not sucesso and not falhas:
        # Formato alternativo: sem listas explícitas, considerar tudo aceito
        sucesso = payload["item_id_list"]
    return sucesso, falhas


# ==============================================================================
# VOUCHER DA LOJA (v2.voucher) — incentivo de checkout contra carrinho abandonado
# ==============================================================================

def _gerar_codigo_voucher() -> str:
    """Código de 5 chars (limite da Shopee BR): 'IA' + 3 chars ALEATÓRIOS.

    O sufixo era derivado do timestamp com ciclo de ~13h — dois vouchers no
    mesmo segundo (ou 13h depois) colidiam e a Shopee rejeitava o segundo.
    """
    alfabeto = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "IA" + "".join(secrets.choice(alfabeto) for _ in range(3))


def criar_voucher_loja(nome, desconto_reais, min_gasto, usos, dias_duracao=7, codigo=None):
    """Cria um voucher de valor FIXO para a loja toda (voucher_type=1,
    reward_type=1 — custo máximo previsível: usos × desconto).

    Começa em ~15 min (a Shopee exige start_time no futuro) e aparece nos
    canais padrão (página da loja, produto e checkout).
    Retorna (True, voucher_id) ou (False, motivo).
    """
    inicio = int(time.time()) + 900
    payload = {
        "voucher_name": str(nome)[:100],
        "voucher_code": (codigo or _gerar_codigo_voucher())[:5].upper(),
        "start_time": inicio,
        "end_time": inicio + int(dias_duracao) * 86400,
        "voucher_type": 1,      # 1 = loja inteira
        "reward_type": 1,       # 1 = desconto em valor fixo
        "usage_quantity": int(usos),
        "min_basket_price": float(min_gasto),
        "discount_amount": float(desconto_reais),
        "display_channel_list": [1],  # 1 = exibir em todos os canais padrão
    }
    logger.info(f"Criando voucher {payload['voucher_code']}: R$ {desconto_reais} acima de R$ {min_gasto}, {usos} usos")
    resp = chamar_shopee_api("/api/v2/voucher/add_voucher", method="POST", payload=payload)
    if resp and resp.get("voucher_id"):
        return True, resp["voucher_id"]
    return False, f"Shopee recusou o voucher: {resp}" if resp else "Sem resposta da Shopee."


def listar_vouchers(status="ongoing"):
    """Vouchers da loja por status ('upcoming'|'ongoing'|'expired'|'all').
    Retorna lista (possivelmente vazia) ou None em falha de comunicação."""
    resp = chamar_shopee_api(
        "/api/v2/voucher/get_voucher_list",
        params={"status": status, "page_no": 1, "page_size": 25},
    )
    if resp is None:
        return None
    return resp.get("voucher_list") or []


def encerrar_voucher(voucher_id, ja_iniciado=True):
    """Encerra um voucher em andamento (end_voucher) ou exclui um agendado
    que ainda não começou (delete_voucher). Retorna (sucesso, msg)."""
    path = "/api/v2/voucher/end_voucher" if ja_iniciado else "/api/v2/voucher/delete_voucher"
    resp = chamar_shopee_api(path, method="POST", payload={"voucher_id": int(voucher_id)})
    if resp is not None and resp.get("voucher_id"):
        return True, "Voucher encerrado."
    return False, f"Falha ao encerrar: {resp}" if resp else "Sem resposta da Shopee."


# ==============================================================================
# MÉTRICAS EXTRAS POR ITEM (v2.product.get_item_extra_info)
# views/curtidas/vendas acumuladas via API — sem depender de planilha
# ==============================================================================

def obter_info_extra_itens(item_ids):
    """Busca views, curtidas e vendas acumuladas por item, em lotes de 50.

    Retorna {item_id: {"views": n, "likes": n, "vendas_acumuladas": n,
    "avaliacoes": n, "estrelas": f}} — apenas itens que a API devolveu.
    """
    resultado = {}
    ids = [int(i) for i in item_ids]
    for inicio in range(0, len(ids), 50):
        lote = ids[inicio:inicio + 50]
        resp = chamar_shopee_api(
            "/api/v2/product/get_item_extra_info",
            params={"item_id_list": ",".join(str(i) for i in lote)},
        )
        for item in (resp or {}).get("item_list", []) or []:
            resultado[item.get("item_id")] = {
                "views": int(item.get("views", 0) or 0),
                "likes": int(item.get("likes", 0) or 0),
                "vendas_acumuladas": int(item.get("sale", 0) or 0),
                "avaliacoes": int(item.get("comment_count", 0) or 0),
                "estrelas": float(item.get("rating_star", 0) or 0),
            }
    return resultado


# ==============================================================================
# PÓS-VENDA E PROMOÇÕES (sondados ao vivo em 18/07/2026 — todos FUNCIONAM
# neste app in-house: returns, discount, bundle_deal, add_on_deal,
# shop_flash_sale, get_tracking_info)
# ==============================================================================

def _promo_status_derivado(inicio, fim):
    """Status temporal uniforme entre as 4 famílias (cada uma tem enum próprio)."""
    agora = int(time.time())
    if inicio and agora < int(inicio):
        return "upcoming"
    if fim and agora > int(fim):
        return "expired"
    return "ongoing"


def _itens_de_promocao(tipo, id_promocao):
    """Itens cobertos por uma promoção. model_id 0 = anúncio inteiro.

    Cada família tem um endpoint de detalhe próprio e formatos levemente
    diferentes; tudo aqui é defensivo — um formato inesperado vira lista vazia,
    nunca uma exceção que derrube a sincronização.
    """
    itens = []
    try:
        if tipo == "DESCONTO":
            pagina = 1
            while True:
                resp = chamar_shopee_api("/api/v2/discount/get_discount", params={
                    "discount_id": id_promocao, "page_no": pagina, "page_size": 100,
                })
                if not resp:
                    break
                for item in resp.get("item_list") or []:
                    modelos = item.get("model_list") or []
                    if modelos:
                        for modelo in modelos:
                            itens.append((int(item.get("item_id", 0)), int(modelo.get("model_id", 0) or 0),
                                          float(modelo.get("model_promotion_price", 0) or 0)))
                    else:
                        itens.append((int(item.get("item_id", 0)), 0,
                                      float(item.get("item_promotion_price", 0) or 0)))
                if not resp.get("more"):
                    break
                pagina += 1
        elif tipo == "COMBO":
            resp = chamar_shopee_api("/api/v2/bundle_deal/get_bundle_deal_item",
                                     params={"bundle_deal_id": id_promocao})
            for item in (resp or {}).get("item_list") or []:
                iid = item.get("item_id") if isinstance(item, dict) else item
                if iid:
                    itens.append((int(iid), 0, None))
        elif tipo == "ADD_ON":
            for endpoint, chave in (
                ("/api/v2/add_on_deal/get_add_on_deal_main_item", "main_item_list"),
                ("/api/v2/add_on_deal/get_add_on_deal_sub_item", "sub_item_list"),
            ):
                resp = chamar_shopee_api(endpoint, params={"add_on_deal_id": id_promocao})
                for item in (resp or {}).get(chave) or []:
                    if isinstance(item, dict) and item.get("item_id"):
                        itens.append((int(item["item_id"]), int(item.get("model_id", 0) or 0),
                                      float(item.get("sub_item_input_price", 0) or 0) or None))
        elif tipo == "FLASH_SALE":
            offset = 0
            while True:
                resp = chamar_shopee_api("/api/v2/shop_flash_sale/get_shop_flash_sale_items", params={
                    "flash_sale_id": id_promocao, "offset": offset, "limit": 100,
                })
                if not resp:
                    break
                modelos = resp.get("models") or []
                for modelo in modelos:
                    if isinstance(modelo, dict) and modelo.get("item_id"):
                        itens.append((int(modelo["item_id"]), int(modelo.get("model_id", 0) or 0),
                                      float(modelo.get("input_promotion_price", 0) or 0) or None))
                if not modelos:
                    for item in resp.get("item_info") or []:
                        if isinstance(item, dict) and item.get("item_id"):
                            itens.append((int(item["item_id"]), 0, None))
                if len(modelos) < 100:
                    break
                offset += 100
    except Exception as exc:
        logger.warning(f"Itens da promoção {tipo}/{id_promocao} não puderam ser lidos: {exc}")
    # Deduplicação preservando o menor preço informado
    unicos = {}
    for iid, mid, preco in itens:
        chave = (iid, mid)
        if chave not in unicos or (preco is not None and (unicos[chave] is None or preco < unicos[chave])):
            unicos[chave] = preco
    return [(iid, mid, preco) for (iid, mid), preco in unicos.items()]


def listar_promocoes_loja(incluir_itens=True):
    """Lê as 4 famílias de promoção da loja e devolve uma lista normalizada:
    {tipo, id_promocao, nome, status, inicio, fim, itens: [(item_id, model_id, preco)]}.
    """
    promocoes = []

    pagina = 1
    while True:
        resp = chamar_shopee_api("/api/v2/discount/get_discount_list", params={
            "discount_status": "all", "page_no": pagina, "page_size": 100,
        })
        if not resp:
            break
        for promo in resp.get("discount_list") or []:
            promocoes.append({
                "tipo": "DESCONTO", "id_promocao": int(promo.get("discount_id", 0)),
                "nome": str(promo.get("discount_name") or "")[:255],
                "inicio": promo.get("start_time"), "fim": promo.get("end_time"),
            })
        if not resp.get("more"):
            break
        pagina += 1

    pagina = 1
    while True:
        resp = chamar_shopee_api("/api/v2/bundle_deal/get_bundle_deal_list", params={
            "page_no": pagina, "page_size": 100,
        })
        if not resp:
            break
        lista = resp.get("bundle_deal_list") or []
        for promo in lista:
            promocoes.append({
                "tipo": "COMBO", "id_promocao": int(promo.get("bundle_deal_id", 0)),
                "nome": str(promo.get("name") or "")[:255],
                "inicio": promo.get("start_time"), "fim": promo.get("end_time"),
            })
        if not resp.get("more"):
            break
        pagina += 1

    pagina = 1
    while True:
        resp = chamar_shopee_api("/api/v2/add_on_deal/get_add_on_deal_list", params={
            "promotion_status": "all", "page_no": pagina, "page_size": 100,
        })
        if not resp:
            break
        for promo in resp.get("add_on_deal_list") or []:
            promocoes.append({
                "tipo": "ADD_ON", "id_promocao": int(promo.get("add_on_deal_id", 0)),
                "nome": str(promo.get("add_on_deal_name") or "")[:255],
                "inicio": promo.get("start_time"), "fim": promo.get("end_time"),
            })
        if not resp.get("more"):
            break
        pagina += 1

    offset = 0
    while True:
        resp = chamar_shopee_api("/api/v2/shop_flash_sale/get_shop_flash_sale_list", params={
            "type": 0, "offset": offset, "limit": 100,
        })
        if not resp:
            break
        lista = resp.get("flash_sale_list") or []
        for promo in lista:
            promocoes.append({
                "tipo": "FLASH_SALE", "id_promocao": int(promo.get("flash_sale_id", 0)),
                "nome": f"Flash sale {promo.get('flash_sale_id')}",
                "inicio": promo.get("start_time"), "fim": promo.get("end_time"),
            })
        if len(lista) < 100:
            break
        offset += 100

    promocoes = [p for p in promocoes if p["id_promocao"]]
    for promo in promocoes:
        promo["status"] = _promo_status_derivado(promo.get("inicio"), promo.get("fim"))
        if incluir_itens:
            promo["itens"] = _itens_de_promocao(promo["tipo"], promo["id_promocao"])
    return promocoes


def listar_devolucoes(time_from=None, time_to=None):
    """Lista devoluções/reembolsos (v2.returns), paginado. Retorna dicts com
    return_sn, order_sn, status, motivo, motivo_texto, valor_reembolso,
    criado_em (epoch) e itens [(item_id, model_id, quantidade)]."""
    devolucoes = []
    pagina = 1
    while True:
        params = {"page_no": pagina, "page_size": 50}
        if time_from:
            params["create_time_from"] = int(time_from)
        if time_to:
            params["create_time_to"] = int(time_to)
        resp = chamar_shopee_api("/api/v2/returns/get_return_list", params=params)
        if not resp:
            break
        for ret in resp.get("return") or []:
            itens = []
            for item in ret.get("item") or []:
                if isinstance(item, dict) and item.get("item_id"):
                    itens.append((int(item["item_id"]), int(item.get("model_id", 0) or 0),
                                  int(item.get("amount", 0) or 0)))
            devolucoes.append({
                "return_sn": str(ret.get("return_sn") or ""),
                "order_sn": str(ret.get("order_sn") or "") or None,
                "status": str(ret.get("status") or "")[:40],
                "motivo": str(ret.get("reason") or "")[:120],
                "motivo_texto": str(ret.get("text_reason") or "") or None,
                "valor_reembolso": float(ret.get("refund_amount", 0) or 0),
                "criado_em": ret.get("create_time"),
                "itens": itens,
            })
        if not resp.get("more"):
            break
        pagina += 1
    return [d for d in devolucoes if d["return_sn"]]


def obter_rastreio_pedido(order_sn):
    """Status logístico atual e o momento da entrega de um pedido.

    Retorna (logistics_status | None, delivered_epoch | None). O delivered vem
    do evento DELIVERED mais recente da linha do tempo de rastreio.
    """
    resp = chamar_shopee_api("/api/v2/logistics/get_tracking_info", params={"order_sn": order_sn})
    if not resp:
        return None, None
    status_atual = str(resp.get("logistics_status") or "") or None
    delivered = None
    for evento in resp.get("tracking_info") or []:
        if str(evento.get("logistics_status") or "").upper() == "DELIVERED":
            momento = int(evento.get("update_time", 0) or 0)
            if momento and (delivered is None or momento > delivered):
                delivered = momento
    return status_atual, delivered