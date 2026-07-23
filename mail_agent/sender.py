"""Отправка писем по SMTP.

Здесь только транспорт. Подтверждение пользователем делается уровнем выше,
в HumanInTheLoopMiddleware — см. agent.py.
"""

import imaplib
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Optional

from .config import MailConfig

# Проверка адреса: не полный RFC 5322, но отсекает опечатки модели
_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]{2,}$")


def validate_recipients(recipients: list[str]) -> list[str]:
    """Проверить адреса. Возвращает список некорректных."""
    return [r for r in recipients if not _EMAIL_RE.match(r.strip())]


def send_via_smtp(
    config: MailConfig,
    to: list[str],
    subject: str,
    body: str,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
) -> str:
    """Отправить письмо. Возвращает Message-ID отправленного.

    in_reply_to: Message-ID письма, на которое отвечаем — тогда письмо
    попадёт в ту же ветку у получателя.
    """
    if not config.smtp_host:
        raise RuntimeError(
            f"SMTP не настроен для {config.imap_host}. "
            "Проверь smtp_host в конфиге провайдера."
        )

    recipients = [r.strip() for r in to if r.strip()]
    if not recipients:
        raise ValueError("Не указан ни один получатель")

    invalid = validate_recipients(recipients)
    if invalid:
        raise ValueError(f"Некорректные адреса: {', '.join(invalid)}")

    msg = EmailMessage()
    msg["From"] = config.sender_address
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    # Сами задаём Message-ID: иначе его проставит сервер и мы не узнаем значение
    msg["Message-ID"] = make_msgid(domain=config.sender_address.split("@")[-1])
    msg.set_content(body)

    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        # References копит всю цепочку, In-Reply-To — только родителя
        msg["References"] = references or in_reply_to

    ctx = ssl.create_default_context()
    if not config.verify_cert:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    # Retry-логика: Gmail блокирует частые подключения
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, context=ctx, timeout=30) as server:
                server.login(config.smtp_login or config.login, config.password)
                server.send_message(msg)
            break
        except (smtplib.SMTPServerDisconnected, ConnectionResetError):
            if attempt < max_retries - 1:
                delay = 5 * (attempt + 1)  # 5, 10, 15, 20 секунд
                time.sleep(delay)
            else:
                raise

    # Сохраняем письмо в папку "Отправленные" через IMAP
    _save_to_sent(config, msg)

    return msg.get("Message-ID", "")


def _save_to_sent(config: MailConfig, msg: EmailMessage) -> None:
    """Сохранить отправленное письмо в папку Sent через IMAP APPEND."""
    try:
        ctx = ssl.create_default_context()
        if not config.verify_cert:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        
        with imaplib.IMAP4_SSL(config.imap_host, context=ctx) as imap:
            imap.login(config.login, config.password)
            
            # Ищем папку Sent
            sent_folders = ["Sent", "Sent Items", "[Gmail]/Sent Mail", "Отправленные"]
            status, folders = imap.list()
            
            if status != "OK":
                return
            
            # Парсим список папок и ищем подходящую
            sent_folder = None
            for folder_line in folders:
                if isinstance(folder_line, bytes):
                    folder_str = folder_line.decode("utf-8", errors="ignore")
                    for folder_name in sent_folders:
                        if folder_name in folder_str:
                            sent_folder = folder_name
                            break
                    if sent_folder:
                        break
            
            if not sent_folder:
                return
            
            # Сохраняем письмо в папку
            msg_bytes = msg.as_bytes()
            imap.append(f'"{sent_folder}"', "\\Seen", imaplib.Time2Internaldate(time.time()), msg_bytes)
    except Exception:
        # Если не удалось сохранить — не критично, письмо уже отправлено
        pass
