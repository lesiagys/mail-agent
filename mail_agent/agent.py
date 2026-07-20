"""Агент для анализа почты.

Каркас как в b2c_daily_researcher_qwen: create_agent + SqliteSaver.
"""

import os
import sqlite3
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from langchain.agents import create_agent
from langgraph.checkpoint.sqlite import SqliteSaver

from .config import MailConfig
from .model import get_model
from .tools import TOOLS, configure

load_dotenv()

SYSTEM_PROMPT = """Ты — ассистент для работы с почтой. Отвечай на русском.

<инструменты>
- list_folders() — список папок ящика.
- list_emails(folder, days, unread_only, sender, subject_contains, limit)
  — список писем с превью текста (1000 символов).
- read_email(uid, folder) — полный текст одного письма.
</инструменты>

<как работать>
1. Фильтруй на стороне сервера через аргументы list_emails
   (sender, subject_contains, days), а не выгружай всё подряд.
2. Начинай с небольшого limit. Увеличивай, только если писем правда не хватило.
3. Превью хватает для тем и общего смысла. Вызывай read_email только когда
   нужны детали конкретного письма.
4. Если папка не найдена — сначала посмотри list_folders, имена бывают
   кириллические и с префиксами.
</как работать>

<ответ>
Опирайся только на то, что реально вернули инструменты. Не придумывай
отправителей, даты и содержание. Если писем не нашлось — так и скажи.
Ссылаясь на письмо, указывай отправителя и тему.
</ответ>

Сегодня: {current_date}
"""


def build_agent(
    config: Optional[MailConfig] = None,
    model: str = "qwen3.6",
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
    )

