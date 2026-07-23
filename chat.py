#!/usr/bin/env python3
"""Диалог с почтовым агентом.

    uv run chat.py                         # интерактивный режим
    uv run chat.py "письма за 3 дня"       # один вопрос
"""

import sys
import uuid

from langgraph.types import Command

from mail_agent.agent import build_agent


def _read_multiline(prompt: str, current: str) -> str:
    """Прочитать текст в несколько строк. Пустой ввод — оставить как было."""
    print(f"{prompt} (пустая строка — оставить, '.' на отдельной строке — конец)")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            break
        if line == ".":
            break
        if not line and not lines:
            return current
        lines.append(line)
    return "\n".join(lines) if lines else current


def _confirm(action: dict) -> dict:
    """Показать письмо и спросить решение.

    Возвращает decision в формате HumanInTheLoopMiddleware.
    """
    print()
    print(action.get("description") or action.get("name", "Действие"))
    print()

    while True:
        try:
            choice = input("[o]тправить / [и]зменить / [н]ет: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            choice = "н"

        if choice in ("о", "o", "y", "да", "yes"):
            return {"type": "approve"}

        if choice in ("н", "n", "нет", "no", ""):
            try:
                why = input("Причина (можно пропустить): ").strip()
            except (EOFError, KeyboardInterrupt):
                why = ""
            return {"type": "reject", "message": why or "Пользователь отклонил отправку."}

        if choice in ("и", "и", "e", "edit"):
            args = dict(action.get("args", {}))

            to = input(f"Кому [{', '.join(args.get('to') or [])}]: ").strip()
            if to:
                args["to"] = [a.strip() for a in to.split(",") if a.strip()]

            subject = input(f"Тема [{args.get('subject', '')}]: ").strip()
            if subject:
                args["subject"] = subject

            args["body"] = _read_multiline("Текст:", args.get("body", ""))

            return {
                "type": "edit",
                "edited_action": {"name": action.get("name", "send_email"), "args": args},
            }

        print("Не понял. Введи 'о', 'и' или 'н'.")


def main() -> int:
    try:
        agent = build_agent()
    except ValueError as e:
        print(f"Ошибка конфигурации: {e}", file=sys.stderr)
        return 1

    # thread_id разделяет диалоги: одна сессия — одна история
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    def ask(question: str) -> None:
        payload = {"messages": [{"role": "user", "content": question}]}

        # Агент прерывается на каждой отправке письма и ждёт решения.
        # Цикл: пока приходит __interrupt__ — спрашиваем и продолжаем.
        while True:
            result = agent.invoke(payload, config=config)

            interrupts = result.get("__interrupt__")
            if not interrupts:
                break

            request = interrupts[0].value
            decisions = [
                _confirm(action)
                for action in request.get("action_requests", [])
            ]
            payload = Command(resume={"decisions": decisions})

        print(f"\n{result['messages'][-1].content}\n")

    if len(sys.argv) > 1:
        ask(" ".join(sys.argv[1:]))
        return 0

    print("Почтовый агент. Пустая строка или Ctrl+C — выход.\n")
    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            return 0
        try:
            ask(question)
        except Exception as e:
            print(f"Ошибка: {type(e).__name__}: {e}\n", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
