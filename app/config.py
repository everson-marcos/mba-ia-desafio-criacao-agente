"""Configuração central: caminhos e variáveis de ambiente."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DADOS_DIR = ROOT_DIR / "dados"  # estado inicial (somente leitura)
DATA_DIR = ROOT_DIR / "data"  # estado mutável (bancos SQLite)
DATA_DIR.mkdir(exist_ok=True)

CONDOMINIO_DB = DATA_DIR / "condominio.db"
SESSIONS_DB_URL = f"sqlite+aiosqlite:///{DATA_DIR / 'sessions.db'}"

APP_NAME = "residencial_aurora"
# Especialistas que gravam dados (reservas, visitantes).
MODEL = os.getenv("MODEL") or "gemini-3.5-flash"
# Agente principal e especialista do regulamento. Um modelo diferente dobra a
# cota por minuto disponível, já que os limites do AI Studio são por modelo.
MODEL_LEVE = os.getenv("MODEL_LEVE") or "gemini-3.5-flash-lite"
