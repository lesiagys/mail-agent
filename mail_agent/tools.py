"""Инструменты агента для работы с почтой.

Подключение живёт в модуле, а не в аргументах инструмента: модель называет
папку и фильтры, но не логин, пароль или хост. Плюс письма отдаются
постранично — иначе объёмный ящик выест контекст на первом же вызове.
"""

import datetime
from typing import Optional

from langchain.tools import tool

from .client import MailClient, MailItem
from .config import MailConfig, get_config

# Тела писем в списке не отдаём — только превью
_PREVIEW_CHARS = 1000
# Верхняя граница на выдачу, даже если модель попросит больше
_MAX_LIMIT = 50

_config: Optional[MailConfig] = None


def configure(config: Optional[MailConfig] = None) -> None:
    """Задать подключение до запуска агента."""
    global _config
    _config = config or get_config()


def _get_config() -> MailConfig:
    if _config is None:
        configure()
    assert _config is not None
    return _config


def _format(item: MailItem, index: int, with_body: bool = False) -> str:
    ts = item.received_time.strftime("%Y-%m-%d %H:%M") if item.received_time else "?"
    lines = [
        f"[{index}] uid={item.uid}",
        f"  Дата: {ts}",
        f"  От: {item.sender}",
        f"  Тема: {item.subject}",
    ]
    if item.attachments:
        lines.append(f"  Вложения: {', '.join(item.attachments)}")
    if item.body:
        if with_body:
            lines.append(f"  Текст:\n{item.body}")
        else:
            preview = " ".join(item.body[:_PREVIEW_CHARS].split())
            suffix = "..." if len(item.body) > _PREVIEW_CHARS else ""
            lines.append(f"  Превью: {preview}{suffix}")
    return "\n".join(lines)


@tool
def list_folders() -> str:
    """Показать список папок в почтовом ящике.

    Вызывай, когда нужно узнать, какие папки существуют, прежде чем
    искать письма в конкретной папке.
    """
    with MailClient(_get_config()) as client:
        folders = client.list_folders()
    if not folders:
        return "Папок не найдено."
    return "Доступные папки:\n" + "\n".join(f"- {f}" for f in folders)


@tool
def list_emails(
    folder: str = "INBOX",
    days: Optional[int] = None,
    unread_only: bool = False,
    sender: Optional[str] = None,
    subject_contains: Optional[str] = None,
    limit: int = 10,
) -> str:
    """Получить список писем с превью текста (первые 1000 символов).

    Вызывай, когда нужно узнать, какие письма пришли, или найти письма
    по отправителю, теме или периоду. Для полного текста конкретного
    письма используй read_email с полученным uid.

    Args:
        folder: Папка. По умолчанию INBOX. Имена смотри через list_folders.
        days: За сколько последних дней. None — без ограничения по дате.
        unread_only: Только непрочитанные.
        sender: Фильтр по адресу отправителя (подстрока).
        subject_contains: Фильтр по теме (подстрока).
        limit: Сколько писем вернуть, максимум 50.
    """
    limit = max(1, min(limit, _MAX_LIMIT))

    # Фильтрацию отдаём серверу — так по сети не едет лишнее
    criteria_parts = []
    if unread_only:
        criteria_parts.append("UNSEEN")
    if days is not None:
        date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime(
            "%d-%b-%Y"
        )
        criteria_parts.append(f'SINCE "{date}"')

    # Кириллица уходит IMAP-литералом, а он в запросе может быть только один
    # и только последним. Поэтому не-ASCII фильтр применяем ровно один:
    # второй (если он тоже не-ASCII) дофильтруем локально.
    literal: Optional[str] = None
    literal_key: Optional[str] = None
    local_sender: Optional[str] = None
    local_subject: Optional[str] = None

    for value, key in ((sender, "FROM"), (subject_contains, "SUBJECT")):
        if not value:
            continue
        if value.isascii():
            criteria_parts.append(f'{key} "{value}"')
        elif literal is None:
            literal, literal_key = value, key
        elif key == "FROM":
            local_sender = value
        else:
            local_subject = value

    # Ключ литерала — строго последний: значение сервер читает сразу за ним
    if literal_key:
        criteria_parts.append(literal_key)

    criteria = " ".join(criteria_parts) if criteria_parts else None
    since = datetime.timedelta(days=days) if days is not None else None

    # Локальный дофильтр требует запаса: сервер вернёт больше, чем нужно
    fetch_limit = limit * 4 if (local_sender or local_subject) else limit

    try:
        with MailClient(_get_config()) as client:
            items = []
            for item in client.fetch(
                folder=folder,
                criteria=criteria,
                since=since,
                limit=fetch_limit,
                literal=literal,
            ):
                if local_sender and local_sender.lower() not in item.sender.lower():
                    continue
                if local_subject and local_subject.lower() not in item.subject.lower():
                    continue
                items.append(item)
                if len(items) >= limit:
                    break
    except RuntimeError as e:
        return f"Ошибка: {e}. Проверь имя папки через list_folders."

    if not items:
        return f"В папке {folder} писем по заданным условиям не найдено."

    header = f"Найдено писем: {len(items)} (папка {folder})"
    return header + "\n\n" + "\n\n".join(
        _format(item, i) for i, item in enumerate(items, 1)
    )


@tool
def read_email(uid: str, folder: str = "INBOX") -> str:
    """Прочитать полный текст письма по его uid.

    uid берётся из результата list_emails. Вызывай, когда превью
    недостаточно и нужен весь текст письма.

    Args:
        uid: Идентификатор письма из list_emails.
        folder: Папка, в которой лежит письмо.
    """
    try:
        with MailClient(_get_config()) as client:
            status, _ = client.imap.select(f'"{folder}"', readonly=True)
            if status != "OK":
                return f"Не удалось открыть папку {folder}."

            status, data = client.imap.uid("FETCH", uid, "(RFC822)")
            if status != "OK" or not data or not isinstance(data[0], tuple):
                return f"Письмо uid={uid} не найдено в папке {folder}."

            import email as email_module

            from .client import parse_mail

            item = parse_mail(email_module.message_from_bytes(data[0][1]), uid)
    except Exception as e:
        return f"Ошибка чтения письма: {type(e).__name__}: {e}"

    return _format(item, 1, with_body=True)


TOOLS = [list_folders, list_emails, read_email]
