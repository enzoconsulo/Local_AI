"""Túnel SSH de IP fixo para as chamadas à Shopee Open API v2.

A Shopee só aceita chamadas vindas de IPs cadastrados na IP Address Whitelist do
app, e o IP da internet residencial muda sem aviso — cada troca derrubava a
integração até alguém recadastrar o IP no Console. Mesma solução do auto-boost
do BTT Pi: toda chamada à Shopee sai por um túnel SSH (SOCKS5 local) até a VM
Oracle de IP fixo, e só o IP da VM fica cadastrado na whitelist.

Configuração no CHAVES_DADOS.env (TUNEL_SSH_HOST vazio = sem túnel, chamada direta):
    TUNEL_SSH_HOST      IP público fixo da VM
    TUNEL_SSH_USUARIO   usuário SSH da VM (padrão: ubuntu)
    TUNEL_SSH_CHAVE     chave privada autorizada na VM (padrão: ~/.ssh/id_shopee_tunnel)
    TUNEL_PORTA_LOCAL   porta do SOCKS5 local (padrão: 1080)

O túnel se auto-gerencia: `garantir_tunel()` sobe o `ssh` em segundo plano quando
a porta local não está aberta. App, workers de linha de comando e a tarefa agendada
(manter_token.py) funcionam sem passo manual, e um túnel que caiu volta sozinho na
próxima chamada.

Rodar direto (`python utils/tunel_shopee.py`) sobe o túnel e confere o IP de saída.
"""

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from loguru import logger

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env")

HOST = os.getenv("TUNEL_SSH_HOST", "").strip()
USUARIO = os.getenv("TUNEL_SSH_USUARIO", "").strip() or "ubuntu"
CHAVE = Path(os.getenv("TUNEL_SSH_CHAVE", "").strip() or "~/.ssh/id_shopee_tunnel").expanduser()
PORTA = int(os.getenv("TUNEL_PORTA_LOCAL", "").strip() or 1080)
LOG_SSH = ROOT_DIR / "tunel_shopee.log"

_ESPERA_SUBIDA_S = 20
# Depois de uma falha, não tenta subir de novo por um tempo: sem isso, cada uma das
# centenas de chamadas de um sync esperaria o timeout de um túnel que não sobe.
_PAUSA_APOS_FALHA_S = 60
_LOCK = threading.Lock()
_ultima_falha = 0.0


def proxies_shopee():
    """Proxies para o `requests` (None = sem túnel configurado, chamada direta)."""
    if not HOST:
        return None
    url = f"socks5h://127.0.0.1:{PORTA}"
    return {"http": url, "https": url}


def _porta_aberta():
    # Porta aberta responde em <1ms; no Windows, porta FECHADA só desiste depois
    # de ~1s de retransmissões — o timeout curto evita pagar isso a cada chamada.
    try:
        with socket.create_connection(("127.0.0.1", PORTA), timeout=0.5):
            return True
    except OSError:
        return False


def _iniciar_ssh():
    comando = [
        "ssh", "-N", "-D", f"127.0.0.1:{PORTA}",
        "-i", str(CHAVE),
        "-o", "BatchMode=yes",             # nunca pede senha/confirmação (roda sem terminal)
        "-o", "IdentitiesOnly=yes",
        "-o", "ExitOnForwardFailure=yes",  # porta ocupada = sai, em vez de ficar inútil
        "-o", "ConnectTimeout=10",
        "-o", "ServerAliveInterval=30",    # conexão morta = sai; a próxima chamada sobe outro
        "-o", "ServerAliveCountMax=3",
        "-o", "StrictHostKeyChecking=accept-new",
        f"{USUARIO}@{HOST}",
    ]
    with open(LOG_SSH, "ab") as log:
        log.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} subindo túnel ---\n".encode("utf-8"))
        log.flush()
        # Processo independente: continua de pé depois que o Python que o iniciou
        # termina (app fechado, worker de CLI, tarefa agendada).
        if os.name == "nt":
            extra = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
        else:
            extra = {"start_new_session": True}
        subprocess.Popen(comando, stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True, **extra)


def garantir_tunel():
    """Garante o túnel de pé antes de uma chamada à Shopee. True = pode chamar."""
    global _ultima_falha
    if not HOST:
        return True
    # Em pausa após falha: nem testa a porta (cada teste de porta fechada custa tempo).
    if time.time() - _ultima_falha < _PAUSA_APOS_FALHA_S:
        return False
    if _porta_aberta():
        return True

    with _LOCK:
        if time.time() - _ultima_falha < _PAUSA_APOS_FALHA_S:
            return False
        if _porta_aberta():
            return True

        if not CHAVE.is_file():
            logger.error(f"Túnel de IP fixo: chave SSH não encontrada em {CHAVE} (TUNEL_SSH_CHAVE no CHAVES_DADOS.env).")
            _ultima_falha = time.time()
            return False

        logger.info(f"🔒 Subindo túnel de IP fixo até {USUARIO}@{HOST} (SOCKS5 em 127.0.0.1:{PORTA})...")
        try:
            _iniciar_ssh()
        except OSError as exc:
            logger.error(f"Túnel de IP fixo: não consegui executar o ssh ({exc}). O OpenSSH do Windows está instalado?")
            _ultima_falha = time.time()
            return False

        limite = time.time() + _ESPERA_SUBIDA_S
        while time.time() < limite:
            if _porta_aberta():
                logger.success("🔒 Túnel de IP fixo de pé.")
                return True
            time.sleep(0.25)

        _ultima_falha = time.time()
        logger.error(
            f"Túnel de IP fixo não subiu em {_ESPERA_SUBIDA_S}s — detalhes do ssh em {LOG_SSH.name}. "
            f"Chamadas à Shopee suspensas por {_PAUSA_APOS_FALHA_S}s."
        )
        return False


def ip_de_saida():
    """IP público que a Shopee enxerga (pelo túnel, se configurado)."""
    return requests.get("https://api.ipify.org", proxies=proxies_shopee(), timeout=15).text.strip()


if __name__ == "__main__":
    if not HOST:
        print("Túnel de IP fixo desligado (TUNEL_SSH_HOST vazio): a Shopee vê o IP da sua internet, que muda sozinho.")
        sys.exit(0)
    if not garantir_tunel():
        sys.exit(1)
    try:
        ip = ip_de_saida()
    except requests.exceptions.RequestException as exc:
        logger.error(f"Túnel de pé, mas não consegui sair pela VM: {exc}")
        sys.exit(1)
    if ip != HOST:
        logger.warning(f"A Shopee vai ver o IP {ip}, não {HOST}: cadastre {ip} na IP Address Whitelist ou confira TUNEL_SSH_HOST.")
        sys.exit(1)
    logger.success(f"A Shopee vai ver o IP fixo {ip} (o cadastrado na whitelist).")
