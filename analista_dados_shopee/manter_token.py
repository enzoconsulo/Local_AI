# Confere (e, com token próprio, renova) o token da Shopee.
#   python manter_token.py
#
# Token próprio (TOKEN_VIA_PI vazio): o refresh_token vence se ficar 30 dias sem
# ser renovado. O run_local.ps1 registra este script como tarefa agendada diária
# do Windows ("Shopee - manter token vivo"): uma renovação por dia (subindo o
# túnel de IP fixo, se configurado) reinicia a contagem. Se o PC estiver
# desligado no horário, a tarefa roda assim que ele ligar.
#
# Token emprestado pelo Pi (TOKEN_VIA_PI preenchido): só confere que o Pi
# empresta o token. A tarefa diária não é necessária e o run_local.ps1 a remove.

import sys
from pathlib import Path

from loguru import logger

ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))
logger.add(ROOT_DIR / "manter_token.log", rotation="1 MB", retention=3)

from utils.shopee_core import obter_access_token

if __name__ == "__main__":
    sys.exit(0 if obter_access_token() else 1)
