"""Агент для анализа почты.

Каркас как в b2c_daily_researcher_qwen: create_agent + SqliteSaver.
"""

import os
import sqlite3
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.sqlite import SqliteSaver

# Версия из langchain, а не из deepagents: у deepagents обязателен
# backend (файловое хранилище для выгрузки контекста), который тут не нужен
from langchain.agents.middleware import SummarizationMiddleware

from .config import MailConfig
from .model import get_model
from .tools import TOOLS, configure

load_dotenv()

SYSTEM_PROMPT = """Ты — ассистент для работы с почтой. Отвечай на русском.
Отвечай только по почте и о том, что относится к письмам, на другие темы не общайся.

<инструменты>
- list_folders() — список папок ящика.
- list_emails(folder, days, unread_only, sender, subject_contains, limit)
  — список писем с превью текста (1000 символов).
- read_email(uid, folder) — полный текст одного письма.
- send_email(to, subject, body, reply_to_uid) — отправить письмо.
  Каждую отправку пользователь подтверждает вручную.
- search_contacts_tool(query) — поиск контактов по имени, email или алиасу.
  Ищет по подстроке в любом месте. Возвращает информацию о контактах:
  имя, email, домен, даты взаимодействия, количество писем, последние темы.
- add_contact_alias(email, alias) — добавить алиас (прозвище) к контакту.
  Используй, когда пользователь называет контакт по-другому.
- remove_contact_alias(email, alias) — удалить алиас у контакта.
  Используй, когда пользователь просит забыть прозвище или оно назначено неверно.
</инструменты>

<контакты>
Контакты автоматически синхронизируются из папок INBOX и Sent.
При поиске контактов используй search_contacts_tool — он ищет по подстроке
в имени, email или алиасах.

Если пользователь называет контакт по-другому - добавь алиас через add_contact_alias. 
Например:
- Пользователь говорит "напиши Максу" → найди контакт maks@example.com → добавь алиас "Макс"
- Пользователь говорит "спроси у бухгалтера" → найди контакт → добавь алиас "бухгалтер"

Это поможет быстрее находить контакты в будущем.
</контакты>

<как работать>
1. Фильтруй на стороне сервера через аргументы list_emails
   (sender, subject_contains, days), а не выгружай всё подряд.
2. Начинай с небольшого limit. Увеличивай, только если писем правда не хватило.
3. Превью хватает для тем и общего смысла. Вызывай read_email только когда
   нужны детали конкретного письма.
4. Если папка не найдена — сначала посмотри list_folders, имена бывают
   кириллические и с префиксами.
</как работать>

<отправка писем>
Вызывай send_email только когда пользователь прямо просит отправить или
ответить. Не отправляй по своей инициативе.

Если считаешь, что информации для отправки недостаточно либо можно ее дополнить - 
уточни у пользователя перед вызовом send_email.

Перед вызовом убедись, что знаешь адрес получателя: бери его из письма
через list_emails или read_email, либо спроси у пользователя. Не угадывай
адреса и не собирай их из имени и фамилии.

Отвечая на письмо, передавай его uid в reply_to_uid: тема и ветка
проставятся сами.

Если отправка отклонена или пользователь просит что-то изменить —
учти правки и вызови send_email заново с обновлёнными параметрами.
</отправка писем>

<ответ>
Опирайся только на то, что реально вернули инструменты. Не придумывай
отправителей, даты и содержание. Если писем не нашлось — так и скажи.
Ссылаясь на письмо, указывай отправителя и тему.
</ответ>

Сегодня: {current_date}
"""

SUMMARY_PROMPT = """Твоя задача - увменьшить общий объем сообщений, не теряя смысл диалога.
Всегда сохраняй предпочтения пользователя.
Сохраняй текущую дату.
Делай краткую выжимку того, какие письма обработаны, какие отправлены.
Неотправленные письма сохраняй в истории дословно, не изменяя ничего.
"""


def _describe_send(tool_call, state, runtime) -> str:
    """Текст, который пользователь увидит перед подтверждением отправки.

    Без него в запросе показывается сырой словарь аргументов — по нему
    трудно решить, отправлять письмо или нет.
    """
    args = tool_call.get("args", {})
    to = args.get("to") or []
    if isinstance(to, str):
        to = [to]

    lines = [
        f"Кому:  {', '.join(to) or '(не указан)'}",
        f"Тема:  {args.get('subject') or '(без темы)'}",
    ]
    reply_to_uid = args.get("reply_to_uid")
    if reply_to_uid and str(reply_to_uid) != "None":
        lines.append(f"Ответ на письмо uid={reply_to_uid}")
    lines += ["", "Текст:", args.get("body") or "(пусто)"]
    return "\n".join(lines)


def build_agent(
    config: Optional[MailConfig] = None,
    model: str = "qwen3.6-dashscope",
    checkpoint_path: str = "db/agent_memory.sqlite",
):
    """Собрать агента.

    config: подключение к почте. None — берётся из .env.
    """
    configure(config)

    os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)
    conn = sqlite3.connect(checkpoint_path, check_same_thread=False, timeout=30.0)

    return create_agent(
        model=get_model(model),
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT.format(
            current_date=datetime.now().strftime("%Y-%m-%d")
        ),
        checkpointer=SqliteSaver(conn),
        middleware=[
            # Отправка необратима — подтверждаем каждый вызов.
            # HITL идёт первым: иначе неподтверждённый вызов может
            # попасть под сжатие истории суммаризацией.
            HumanInTheLoopMiddleware(
                interrupt_on={
                    "send_email": {
                        "allowed_decisions": ["approve", "edit", "reject"],
                        "description": _describe_send,
                    }
                }
            ),
            SummarizationMiddleware(
                model=get_model(model),
                summary_prompt=SUMMARY_PROMPT,
                trigger=("tokens", 20000),
                keep=("messages", 20),
                trim_tokens_to_summarize=None
            )
        ]
    )

