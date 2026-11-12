"""Ponto de entrada do `adk web` (somente desenvolvimento).

Reaproveita os agentes da API. O `adk web` cria sessões sem state, então aqui,
e só aqui, o apartamento da sessão é preenchido a partir de
ADK_WEB_APARTAMENTO (padrão "101"). A API (app/main.py) não usa este arquivo:
lá o apartamento vem exclusivamente de POST /sessoes.

Uso (na raiz do projeto):
    uv run adk web adk_web
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from google.adk.agents.callback_context import CallbackContext  # noqa: E402

from app import db  # noqa: E402
from app.agents import root_agent  # noqa: E402
from app.tools._comum import CHAVE_APARTAMENTO  # noqa: E402

db.inicializar()

_APARTAMENTO_DEV = os.getenv("ADK_WEB_APARTAMENTO", "101")


def _apartamento_da_sessao_dev(callback_context: CallbackContext) -> None:
    if not callback_context.state.get(CHAVE_APARTAMENTO):
        callback_context.state[CHAVE_APARTAMENTO] = _APARTAMENTO_DEV
    return None


root_agent.before_agent_callback = _apartamento_da_sessao_dev

__all__ = ["root_agent"]
