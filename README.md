# Residencial Aurora — assistente virtual com Google ADK

API em Python (FastAPI + Google ADK 2.14.0 + Gemini) do assistente dos moradores do Residencial Aurora: reservas de áreas comuns, autorização de visitantes e dúvidas sobre o regulamento. O modelo conduz a conversa; as regras críticas estão no código.

## Arquitetura

```
FastAPI (app/main.py)
   │  Runner + App (ADK)  ── DatabaseSessionService (SQLite: data/sessions.db)
   ▼
assistente_aurora  (agente principal)
 ├── reservas_agent     sub_agent, acionado por transferência
 ├── visitantes_agent   sub_agent, acionado por transferência
 └── regulamento_agent  AgentTool, acionado como tool
            │
     tools (app/tools/*) ── SQLite de domínio (data/condominio.db)
```

| Agente | Responsabilidade | Como é acionado | Por quê |
|---|---|---|---|
| `assistente_aurora` | Recebe o morador, entende o pedido e distribui. Não tem tools de escrita nem o regulamento nas instruções. | Raiz do `App` | Mantém o prompt principal enxuto e barato; só decide o caminho. |
| `reservas_agent` | Listar áreas, verificar disponibilidade, listar/reservar/cancelar reservas do próprio apartamento. | `sub_agents` (transferência) | Conversas de reserva têm várias trocas (qual área? qual data?) e pedem confirmação. Como sub_agent, ele é o autor do pedido de confirmação, e o Runner devolve a resposta da confirmação a ele, que reexecuta a tool. |
| `visitantes_agent` | Listar e autorizar visitantes do próprio apartamento. | `sub_agents` (transferência) | Mesmo motivo: precisa pausar em confirmação e ser retomado pelo Runner. |
| `regulamento_agent` | Responder dúvidas lendo apenas o capítulo pertinente do regulamento. | `AgentTool` | O `AgentTool` roda o especialista numa sessão isolada em memória. A leitura do capítulo fica lá; só a resposta final volta para a sessão do morador. |

Os dados ficam em SQLite (`data/condominio.db`), criado e carregado a partir de `dados/*.json` (que nunca são alterados). Reservas e visitantes são sempre lidos e gravados por tools (`app/tools/`), e as rotas de verificação leem o mesmo banco sem passar pelo modelo.

## Garantias

### Garantia 1 — cobrança ou acesso só com confirmação

- [app/tools/_comum.py](app/tools/_comum.py) — `pedir_ou_ler_confirmacao` (linha 31): se `tool_context.tool_confirmation` está vazio, chama `tool_context.request_confirmation(...)` e a tool retorna **sem gravar**. Só grava quando o ADK reexecuta a tool com a confirmação preenchida, e se `confirmed` for falso não grava nada.
- [app/tools/reservas.py](app/tools/reservas.py) — `reservar_area`, `if area_info["taxa"] > 0:` (linha 69): só área com taxa pede confirmação; quadra (taxa 0) grava direto.
- [app/tools/visitantes.py](app/tools/visitantes.py) — `autorizar_visitante` (linha 15; pedido de confirmação na linha 34): sempre pede confirmação.
- [app/main.py](app/main.py) — `confirmacoes_pendentes` (linha 77): pendências calculadas a partir dos **eventos persistidos** (function call `adk_request_confirmation` sem function response com o mesmo id). `responder_confirmacao` (linha 156) responde `409` se o id não está nessa lista (`if corpo.id not in ids_pendentes`, linha 161), o que cobre id inexistente, de outra sessão e já respondido; senão envia o `FunctionResponse` ao Runner, que retoma o agente autor.

Por que não depende do modelo: o único jeito de `tool_confirmation` existir é a API enviar o `FunctionResponse` do `adk_request_confirmation`, o que só a rota de confirmações faz. Texto no chat ("já estou confirmando") não preenche esse campo.

### Garantia 2 — cada sessão pertence a um apartamento

- [app/main.py](app/main.py) — `criar_sessao`, `state={CHAVE_APARTAMENTO: apartamento}` (linha 142): o apartamento é gravado uma vez no state, na criação. Nenhuma rota ou tool o altera depois.
- [app/tools/_comum.py](app/tools/_comum.py) — `apartamento_da_sessao` (linha 11): todas as tools leem o apartamento de `tool_context.state`. **Nenhuma tool tem parâmetro de apartamento**, então o modelo não tem como escolher outro.
- [app/db.py](app/db.py) — `cancelar_reserva` (linha 196): o `UPDATE` filtra por apartamento da sessão; reserva de outro apartamento devolve "não encontrada" sem revelar nada.
- [app/tools/reservas.py](app/tools/reservas.py) — `verificar_disponibilidade` (linha 29; retorno na linha 40): devolve só `livre`/`ocupada`, nunca código nem apartamento.

Por que não depende do modelo: mesmo que o modelo acredite que o morador é do 302, as tools só enxergam o apartamento do state.

### Garantia 3 — nada se perde no reinício

- [app/main.py](app/main.py) — `session_service = DatabaseSessionService(...)` (linha 26): sessões e eventos em `data/sessions.db`.
- [app/db.py](app/db.py) — `inicializar` (linha 74): ao subir, só cria o schema; carrega os JSON apenas se o banco estiver vazio. Reiniciar não reseta dados.
- Como as confirmações pendentes vêm dos eventos persistidos, uma pendência criada antes do reinício pode ser aprovada depois.

### Garantia 4 — o regulamento é consultado, não carregado

- [app/tools/regulamento.py](app/tools/regulamento.py) — `consultar_capitulo` (linha 34): fatia `dados/regulamento.md` por `## Capítulo` e devolve **um** capítulo.
- [app/agents.py](app/agents.py) — `AgentTool(agent=regulamento_agent)` (linha 122): o especialista roda em sessão isolada (o `AgentTool` usa `InMemorySessionService` próprio); só a resposta final vira evento na sessão do morador. O índice de capítulos fica na instrução do especialista; o agente principal não recebe o regulamento.

### Garantia 5 — dois moradores, uma reserva

- [app/db.py](app/db.py) — `CREATE UNIQUE INDEX ... ux_reserva_ativa ON reservas(area, data) WHERE status = 'ativa'` (linha 44): a exclusividade é do banco, validada atomicamente no `INSERT`.
- [app/db.py](app/db.py) — `criar_reserva` (linha 172) converte o `IntegrityError` em `ReservaIndisponivel`, e [app/tools/reservas.py](app/tools/reservas.py) (linha 88) devolve `indisponivel` como resposta normal (HTTP 200).
- Cancelar não apaga a linha (`status = 'cancelada'`) e `codigo` é chave primária, então nenhum código se repete (regra 5).

A conferência de agenda feita antes (`area_ocupada`) é só para responder rápido; quem decide é o índice no instante da gravação.

## Como rodar

Pré-requisitos: Python 3.12+, [uv](https://docs.astral.sh/uv/) e uma chave do Google AI Studio.

1. Variáveis de ambiente:

   ```bash
   cp .env.example .env
   ```

   | Variável | Descrição |
   |---|---|
   | `GOOGLE_API_KEY` | Chave do Google AI Studio |
   | `GOOGLE_GENAI_USE_VERTEXAI` | `FALSE` (usa AI Studio) |
   | `MODEL` | Modelo dos especialistas de reservas e visitantes (opcional; padrão: `gemini-3.5-flash`) |
   | `MODEL_LEVE` | Modelo do agente principal e do especialista de regulamento (opcional; padrão: `gemini-3.5-flash-lite`) |

2. Instalar dependências:

   ```bash
   uv sync
   ```

3. Restaurar os dados iniciais (reservas e visitantes voltam a `dados/*.json`; as sessões são mantidas):

   ```bash
   uv run python scripts/restore.py
   ```

   Para também apagar as sessões, com a API parada: `uv run python scripts/restore.py --sessoes`.

4. Subir a API em `http://localhost:8000`:

   ```bash
   uv run uvicorn app.main:app --port 8000
   ```

Não há serviço externo: os dois bancos SQLite ficam em `data/` (fora do Git).

### Desenvolvimento com `adk web` (opcional)

Para ver transferências, chamadas de tool e pedidos de confirmação na interface do ADK:

```bash
uv run adk web adk_web --port 8010
```

Abra `http://localhost:8010` e escolha `aurora`. Como o `adk web` cria sessões sem state, o ponto de entrada [adk_web/aurora/agent.py](adk_web/aurora/agent.py) preenche o apartamento a partir de `ADK_WEB_APARTAMENTO` (padrão `101`). Isso vale só nesse modo; a API não usa esse arquivo.
