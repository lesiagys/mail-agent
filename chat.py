#!/usr/bin/env python3
"""Диалог с почтовым агентом.

    uv run chat.py                         # интерактивный режим
    uv run chat.py "письма за 3 дня"       # один вопрос
"""

import sys
import uuid

from mail_agent.agent import build_agent


def main() -> int:
    try:
        agent = build_agent()
    except ValueError as e:
        print(f"Ошибка конфигурации: {e}", file=sys.stderr)
        return 1

    # thread_id разделяет диалоги: одна сессия — одна история
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    def ask(question: str) -> None:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": question}]},
            config=config,
        )
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
