"""Armazenamento dos dados do condomínio (SQLite).

Os arquivos de `dados/` são o estado inicial e nunca são alterados. As mudanças
feitas pelo assistente ficam em `data/condominio.db`.

Exclusividade de reserva (Garantia 5): o índice único parcial
`ux_reserva_ativa` impede, no próprio banco e no instante do INSERT, que
existam duas reservas ativas para a mesma área na mesma data. Não depende de
nenhuma conferência anterior feita pela aplicação.

Unicidade de código (regra 5): `codigo` é PRIMARY KEY e cancelar não apaga a
linha (só muda `status`), então um código já usado nunca volta a ser gerado.
"""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from typing import Iterator

from app.config import CONDOMINIO_DB, DADOS_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS areas (
    id    TEXT PRIMARY KEY,
    nome  TEXT NOT NULL,
    taxa  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS apartamentos (
    numero  TEXT PRIMARY KEY,
    morador TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reservas (
    codigo      TEXT PRIMARY KEY,
    apartamento TEXT NOT NULL,
    area        TEXT NOT NULL REFERENCES areas(id),
    data        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ativa' CHECK (status IN ('ativa', 'cancelada'))
);

-- Garantia 5: no máximo uma reserva ATIVA por (área, data), validado na gravação.
CREATE UNIQUE INDEX IF NOT EXISTS ux_reserva_ativa
    ON reservas(area, data) WHERE status = 'ativa';

CREATE TABLE IF NOT EXISTS visitantes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    apartamento TEXT NOT NULL,
    nome        TEXT NOT NULL,
    data        TEXT NOT NULL
);
"""


class ReservaIndisponivel(Exception):
    """A área já tem reserva ativa na data pedida."""


@contextmanager
def conectar() -> Iterator[sqlite3.Connection]:
    """Abre uma conexão curta; commit ao sair sem erro, rollback em caso de erro."""
    conn = sqlite3.connect(CONDOMINIO_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def inicializar() -> None:
    """Cria o schema se ainda não existir; carrega os dados iniciais só se o banco estiver vazio."""
    with conectar() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        vazio = conn.execute("SELECT COUNT(*) FROM areas").fetchone()[0] == 0
    if vazio:
        restaurar()


def restaurar() -> None:
    """Volta reservas e visitantes ao estado de `dados/*.json`."""
    def ler(nome: str):
        return json.loads((DADOS_DIR / nome).read_text(encoding="utf-8"))

    with conectar() as conn:
        conn.executescript(
            "DROP TABLE IF EXISTS reservas; DROP TABLE IF EXISTS visitantes;"
            "DROP TABLE IF EXISTS apartamentos; DROP TABLE IF EXISTS areas;"
        )
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO areas (id, nome, taxa) VALUES (:id, :nome, :taxa)",
            ler("areas.json"),
        )
        conn.executemany(
            "INSERT INTO apartamentos (numero, morador) VALUES (:numero, :morador)",
            ler("apartamentos.json"),
        )
        conn.executemany(
            "INSERT INTO reservas (codigo, apartamento, area, data) "
            "VALUES (:codigo, :apartamento, :area, :data)",
            ler("reservas.json"),
        )
        conn.executemany(
            "INSERT INTO visitantes (apartamento, nome, data) VALUES (:apartamento, :nome, :data)",
            ler("visitantes.json"),
        )


# --------------------------------------------------------------------------
# Consultas
# --------------------------------------------------------------------------

def listar_areas() -> list[dict]:
    with conectar() as conn:
        rows = conn.execute("SELECT id, nome, taxa FROM areas ORDER BY nome").fetchall()
    return [dict(r) for r in rows]


def buscar_area(area_id: str) -> dict | None:
    with conectar() as conn:
        row = conn.execute("SELECT id, nome, taxa FROM areas WHERE id = ?", (area_id,)).fetchone()
    return dict(row) if row else None


def apartamento_existe(numero: str) -> bool:
    with conectar() as conn:
        row = conn.execute("SELECT 1 FROM apartamentos WHERE numero = ?", (numero,)).fetchone()
    return row is not None


def area_ocupada(area_id: str, data: str) -> bool:
    with conectar() as conn:
        row = conn.execute(
            "SELECT 1 FROM reservas WHERE area = ? AND data = ? AND status = 'ativa'",
            (area_id, data),
        ).fetchone()
    return row is not None


def reservas_do_apartamento(apartamento: str) -> list[dict]:
    with conectar() as conn:
        rows = conn.execute(
            "SELECT codigo, area, data FROM reservas "
            "WHERE apartamento = ? AND status = 'ativa' ORDER BY data, area",
            (apartamento,),
        ).fetchall()
    return [dict(r) for r in rows]


def visitantes_do_apartamento(apartamento: str) -> list[dict]:
    with conectar() as conn:
        rows = conn.execute(
            "SELECT nome, data FROM visitantes WHERE apartamento = ? ORDER BY data, id",
            (apartamento,),
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Gravações
# --------------------------------------------------------------------------

def _novo_codigo() -> str:
    return f"RSV-{uuid.uuid4().hex[:8].upper()}"


def criar_reserva(apartamento: str, area_id: str, data: str) -> str:
    """Grava a reserva e devolve o código.

    A exclusividade é garantida pelo índice único `ux_reserva_ativa`: se outra
    reserva ativa para (área, data) entrou antes, o INSERT falha atomicamente e
    levantamos `ReservaIndisponivel`.
    """
    for _ in range(5):
        codigo = _novo_codigo()
        try:
            with conectar() as conn:
                conn.execute(
                    "INSERT INTO reservas (codigo, apartamento, area, data, status) "
                    "VALUES (?, ?, ?, ?, 'ativa')",
                    (codigo, apartamento, area_id, data),
                )
            return codigo
        except sqlite3.IntegrityError as exc:
            if "reservas.codigo" in str(exc):
                continue  # colisão de código (improvável): gera outro
            raise ReservaIndisponivel() from exc
    raise RuntimeError("Não foi possível gerar um código de reserva único.")


def cancelar_reserva(apartamento: str, area_id: str, data: str) -> str | None:
    """Cancela a reserva ativa do PRÓPRIO apartamento. Devolve o código ou None."""
    with conectar() as conn:
        row = conn.execute(
            "SELECT codigo FROM reservas "
            "WHERE apartamento = ? AND area = ? AND data = ? AND status = 'ativa'",
            (apartamento, area_id, data),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE reservas SET status = 'cancelada' WHERE codigo = ? AND apartamento = ?",
            (row["codigo"], apartamento),
        )
    return row["codigo"]


def autorizar_visitante(apartamento: str, nome: str, data: str) -> None:
    with conectar() as conn:
        conn.execute(
            "INSERT INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)",
            (apartamento, nome, data),
        )
