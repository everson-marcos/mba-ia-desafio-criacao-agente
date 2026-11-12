"""Restaura reservas e visitantes ao estado de `dados/*.json`.

Uso:
    uv run python scripts/restore.py            # só os dados do condomínio
    uv run python scripts/restore.py --sessoes  # também apaga as sessões
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.config import DATA_DIR  # noqa: E402


def main() -> None:
    db.restaurar()
    print("Dados do condomínio restaurados a partir de dados/*.json.")
    if "--sessoes" in sys.argv:
        for nome in ("sessions.db", "sessions.db-wal", "sessions.db-shm"):
            (DATA_DIR / nome).unlink(missing_ok=True)
        print("Sessões apagadas.")


if __name__ == "__main__":
    main()
