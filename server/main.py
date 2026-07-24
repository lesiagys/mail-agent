"""FastAPI-сервер для почтового агента."""

import json
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# Добавляем родительскую директорию в path для импорта mail_agent
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel
from typing import Optional

from mail_agent.agent import build_agent

# Сообщение с таким префиксом — не текст пользователю, а решение по interrupt
# (approve/reject/edit), которое фронтенд отправляет по клику на кнопку.
DECISION_MARKER = "__INTERRUPT_DECISION__:"

# Глобальный инстанс агента и конфиг сессии
agent = None
session_config = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация агента при запуске сервера."""
    global agent, session_config
    try:
        agent = build_agent()
        session_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        print("✓ Агент инициализирован")
    except Exception as e:
        print(f"✗ Ошибка инициализации агента: {e}", file=sys.stderr)
        raise
    yield


app = FastAPI(title="Mail Agent API", lifespan=lifespan)


class ChatRequest(BaseModel):
    messages: list[dict]


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Отправить сообщение агенту и получить стриминг-ответ."""
    if agent is None:
        raise HTTPException(status_code=500, detail="Агент не инициализирован")

    try:
        # Логируем входящие сообщения для отладки
        print(f"[DEBUG] Получено сообщений: {len(request.messages)}")
        for i, msg in enumerate(request.messages):
            print(f"[DEBUG] Сообщение {i}: {msg}")

        # Фильтруем и преобразуем сообщения в формат OpenAI (role + content)
        valid_messages = []
        for msg in request.messages:
            if not isinstance(msg, dict) or 'role' not in msg:
                print(f"[DEBUG] Пропущено сообщение без role: {msg}")
                continue
            
            # assistant-ui использует 'parts' вместо 'content'
            if 'content' in msg:
                content = msg['content']
            elif 'parts' in msg:
                # Преобразуем parts в текст
                parts = msg['parts']
                if isinstance(parts, list):
                    # Берём только текстовые части
                    text_parts = [p.get('text', '') for p in parts if isinstance(p, dict) and p.get('type') == 'text']
                    content = ''.join(text_parts)
                else:
                    content = str(parts)
            else:
                print(f"[DEBUG] Пропущено сообщение без content/parts: {msg}")
                continue
            
            valid_messages.append({'role': msg['role'], 'content': content})

        if not valid_messages:
            raise HTTPException(status_code=400, detail="Нет валидных сообщений")

        # Сообщение-решение по interrupt (approve/reject/edit) — резюмируем
        # граф вместо того, чтобы отправлять его как новый ход диалога.
        last = valid_messages[-1]
        if last["role"] == "user" and last["content"].startswith(DECISION_MARKER):
            decision_payload = json.loads(last["content"][len(DECISION_MARKER):])
            decisions = (
                decision_payload if isinstance(decision_payload, list) else [decision_payload]
            )
            print(f"[DEBUG] Резюмирую interrupt решениями: {decisions}")
            stream_input = Command(resume={"decisions": decisions})
        else:
            print(f"[DEBUG] Вызываю агент с {len(valid_messages)} сообщениями")
            stream_input = {"messages": valid_messages}

        # Возвращаем в формате AI SDK UI Message Stream (SSE). Генератор —
        # обычная (не async) функция: agent.stream() блокирующий, а Starlette
        # сам уводит синхронные генераторы в threadpool, не блокируя event loop.
        def generate():
            def sse(obj):
                return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

            text_id = str(uuid.uuid4())
            text_started = False
            yield sse({"type": "start"})
            yield sse({"type": "start-step"})

            try:
                # stream_mode="messages" отдаёт токены по мере генерации.
                # Стримим только узел "model" — основной ответ агента;
                # узел "tools" отдаёт результаты инструментов одним куском,
                # узел суммаризации сообщений — служебный, наружу не идёт.
                for chunk, metadata in agent.stream(
                    stream_input, config=session_config, stream_mode="messages"
                ):
                    if metadata.get("langgraph_node") != "model":
                        continue
                    delta = getattr(chunk, "content", None)
                    if not delta or not isinstance(delta, str):
                        continue
                    if not text_started:
                        yield sse({"type": "text-start", "id": text_id})
                        text_started = True
                    yield sse({"type": "text-delta", "id": text_id, "delta": delta})

                # После стрима проверяем состояние графа: если он встал на
                # interrupt (запрос на подтверждение отправки), добавляем
                # карточку с данными для кнопок.
                approval_data = None
                state = agent.get_state(session_config)
                for task in state.tasks:
                    if task.interrupts:
                        interrupt_value = task.interrupts[0].value
                        approval_data = {
                            "action_requests": interrupt_value.get("action_requests", []),
                            "review_configs": interrupt_value.get("review_configs", []),
                        }
                        break

                if approval_data is not None:
                    # Снаружи карточки — только статичный вопрос, все детали
                    # (кому/тема/текст) показываются внутри самой карточки.
                    if not text_started:
                        yield sse({"type": "text-start", "id": text_id})
                        text_started = True
                    yield sse(
                        {"type": "text-delta", "id": text_id, "delta": "Отправить письмо?"}
                    )

                if not text_started:
                    yield sse({"type": "text-start", "id": text_id})
                    text_started = True
                yield sse({"type": "text-end", "id": text_id})
                if approval_data is not None:
                    yield sse({"type": "data-approval", "data": approval_data})
            except Exception as e:
                print(f"[DEBUG] Ошибка стриминга: {e}", file=sys.stderr)
                yield sse({"type": "error", "errorText": f"Ошибка агента: {e}"})

            yield sse({"type": "finish-step"})
            yield sse({"type": "finish"})
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"x-vercel-ai-ui-message-stream": "v1"},
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка агента: {str(e)}")


@app.get("/health")
async def health():
    """Проверка работоспособности сервера."""
    return {"status": "ok", "agent_ready": agent is not None}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
