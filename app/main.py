"""API do assistente do Residencial Aurora (FastAPI + Google ADK Runner)."""

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from google.adk.apps import App
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService, Session
from google.genai import types
from pydantic import BaseModel

from app import db
from app.agents import root_agent
from app.config import APP_NAME, SESSIONS_DB_URL
from app.tools._comum import CHAVE_APARTAMENTO

# Nome do function call que o ADK emite quando uma tool pede confirmação.
REQUEST_CONFIRMATION = "adk_request_confirmation"
# O apartamento fica no state da sessão; o user_id do ADK é fixo.
USER_ID = "morador"

# Garantia 3: sessões e eventos persistidos em SQLite, sobrevivem ao reinício.
session_service = DatabaseSessionService(
    db_url=SESSIONS_DB_URL, connect_args={"timeout": 30}
)
adk_app = App(name=APP_NAME, root_agent=root_agent)
runner = Runner(app=adk_app, session_service=session_service)

# Serializa as execuções de uma mesma sessão (mensagem e confirmação), para que
# a verificação "está pendente?" e a retomada aconteçam sem intercalação.
_locks_sessao: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.inicializar()
    yield


api = FastAPI(title="Residencial Aurora", lifespan=lifespan)
app = api  # alvo do uvicorn: app.main:app


# --------------------------------------------------------------------------
# Modelos de entrada
# --------------------------------------------------------------------------

class NovaSessao(BaseModel):
    apartamento: str


class Mensagem(BaseModel):
    texto: str


class RespostaConfirmacao(BaseModel):
    id: str
    confirmado: bool


# --------------------------------------------------------------------------
# Apoio
# --------------------------------------------------------------------------

async def _sessao_ou_404(session_id: str) -> Session:
    sessao = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    if sessao is None:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    return sessao


def confirmacoes_pendentes(sessao: Session) -> list[dict]:
    """Garantia 1: pendências derivadas dos EVENTOS persistidos da sessão.

    Uma confirmação está pendente quando existe o function call
    `adk_request_confirmation` e ainda não existe function response com o mesmo
    id. Por vir dos eventos, a lista sobrevive ao reinício da API, e uma
    confirmação já respondida deixa de constar (reenvio => 409).
    """
    pedidos: dict[str, types.FunctionCall] = {}
    respondidos: set[str] = set()
    for evento in sessao.events:
        for fc in evento.get_function_calls():
            if fc.name == REQUEST_CONFIRMATION and fc.id:
                pedidos[fc.id] = fc
        for fr in evento.get_function_responses():
            if fr.id:
                respondidos.add(fr.id)

    pendentes = []
    for fc_id, fc in pedidos.items():
        if fc_id in respondidos:
            continue
        args = fc.args or {}
        payload = (args.get("toolConfirmation") or {}).get("payload") or {}
        original = args.get("originalFunctionCall") or {}
        pendentes.append(
            {
                "id": fc_id,
                "acao": payload.get("acao") or original.get("name", ""),
                "detalhes": payload.get("detalhes") or original.get("args", {}),
            }
        )
    return pendentes


def _textos(evento: Event) -> list[str]:
    if evento.author == "user" or evento.partial or not evento.content or not evento.content.parts:
        return []
    return [p.text for p in evento.content.parts if p.text and not p.thought]


async def _executar(session_id: str, conteudo: types.Content) -> dict:
    textos: list[str] = []
    async for evento in runner.run_async(
        user_id=USER_ID, session_id=session_id, new_message=conteudo
    ):
        textos.extend(_textos(evento))
    sessao = await _sessao_ou_404(session_id)
    return {
        "resposta": "\n".join(t.strip() for t in textos if t.strip()),
        "confirmacoes_pendentes": confirmacoes_pendentes(sessao),
    }


# --------------------------------------------------------------------------
# Rotas de conversa
# --------------------------------------------------------------------------

@api.post("/sessoes", status_code=201)
async def criar_sessao(corpo: NovaSessao) -> dict:
    apartamento = corpo.apartamento.strip()
    if not db.apartamento_existe(apartamento):
        raise HTTPException(status_code=422, detail="Apartamento inexistente.")
    # Garantia 2: o apartamento é gravado UMA vez no state, na criação da sessão.
    sessao = await session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, state={CHAVE_APARTAMENTO: apartamento}
    )
    return {"session_id": sessao.id}


@api.post("/sessoes/{session_id}/mensagens")
async def enviar_mensagem(session_id: str, corpo: Mensagem) -> dict:
    await _sessao_ou_404(session_id)
    conteudo = types.Content(role="user", parts=[types.Part(text=corpo.texto)])
    async with _locks_sessao[session_id]:
        return await _executar(session_id, conteudo)


@api.post("/sessoes/{session_id}/confirmacoes")
async def responder_confirmacao(session_id: str, corpo: RespostaConfirmacao) -> dict:
    await _sessao_ou_404(session_id)
    async with _locks_sessao[session_id]:
        sessao = await _sessao_ou_404(session_id)
        ids_pendentes = {p["id"] for p in confirmacoes_pendentes(sessao)}
        if corpo.id not in ids_pendentes:
            raise HTTPException(
                status_code=409,
                detail="Não existe confirmação pendente com esse id nesta sessão.",
            )
        # Retomada: FunctionResponse para o adk_request_confirmation pendente.
        # O Runner roteia a resposta ao agente autor do pedido, que reexecuta a
        # tool com tool_context.tool_confirmation preenchido.
        conteudo = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=corpo.id,
                        name=REQUEST_CONFIRMATION,
                        response={"confirmed": corpo.confirmado},
                    )
                )
            ],
        )
        return await _executar(session_id, conteudo)


@api.get("/sessoes/{session_id}/eventos")
async def listar_eventos(session_id: str) -> list[dict]:
    sessao = await _sessao_ou_404(session_id)
    return [e.model_dump(mode="json", exclude_none=True, by_alias=True) for e in sessao.events]


# --------------------------------------------------------------------------
# Rotas de verificação (leem o banco direto, sem o modelo)
# --------------------------------------------------------------------------

@api.get("/apartamentos/{numero}/reservas")
async def reservas_do_apartamento(numero: str) -> list[dict]:
    return db.reservas_do_apartamento(numero)


@api.get("/apartamentos/{numero}/visitantes")
async def visitantes_do_apartamento(numero: str) -> list[dict]:
    return db.visitantes_do_apartamento(numero)
