"""IMAP-клиент для получения списка писем.

Провайдер-агностичен: работает и с Gmail, и с внутренним контуром —
разница только в MailConfig.
"""

import base64
import datetime
import email
import imaplib
import ssl
import time
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Iterator, Optional

from .cleaner import clean_email_body
from .config import MailConfig


@dataclass
class MailItem:
    """Одно письмо в списке."""

    uid: str
    sender: str
    subject: str
    received_time: Optional[datetime.datetime]
    message_id: str
    body: str = ""
    attachments: list[str] = field(default_factory=list)
    recipients: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        ts = self.received_time.strftime("%Y-%m-%d %H:%M") if self.received_time else "?"
        return f"<MailItem {ts} | {self.sender[:40]} | {self.subject[:50]}>"


def decode_imap_utf7(name: str) -> str:
    """Имя IMAP-папки -> читаемая строка (RFC 3501, modified UTF-7).

    Отличия от обычного UTF-7: сдвиг начинается с '&', а не '+',
    и в base64 используется ',' вместо '/'.

        >>> decode_imap_utf7("[Gmail]/&BCEEPwQwBDw-")
        '[Gmail]/Спам'
    """
    if "&" not in name:
        return name

    result = []
    i = 0
    while i < len(name):
        char = name[i]
        if char != "&":
            result.append(char)
            i += 1
            continue

        end = name.find("-", i + 1)
        if end == -1:
            # Незакрытая последовательность — отдаём как есть
            result.append(name[i:])
            break

        chunk = name[i + 1 : end]
        if not chunk:
            result.append("&")  # "&-" — экранированный амперсанд
        else:
            try:
                b64 = chunk.replace(",", "/")
                b64 += "=" * (-len(b64) % 4)
                result.append(base64.b64decode(b64).decode("utf-16-be"))
            except Exception:
                result.append(name[i : end + 1])
        i = end + 1

    return "".join(result)


def encode_imap_utf7(name: str) -> str:
    """Читаемое имя папки -> modified UTF-7, чтобы передать серверу."""
    if all(0x20 <= ord(c) <= 0x7E and c != "&" for c in name):
        return name

    result = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        raw = "".join(buffer).encode("utf-16-be")
        b64 = base64.b64encode(raw).decode("ascii").rstrip("=")
        result.append("&" + b64.replace("/", ",") + "-")
        buffer.clear()

    for char in name:
        if char == "&":
            flush()
            result.append("&-")
        elif 0x20 <= ord(char) <= 0x7E:
            flush()
            result.append(char)
        else:
            buffer.append(char)

    flush()
    return "".join(result)


def _parse_list_line(line: str) -> str:
    """Достаёт имя папки из ответа LIST: (флаги) "/" "имя"."""
    if line.endswith('"'):
        start = line.rfind('"', 0, -1)
        if start != -1:
            return line[start + 1 : -1]
    # Имя без кавычек — берём последний токен
    parts = line.rsplit(" ", 1)
    return parts[-1] if len(parts) == 2 else ""


def _decode_mime(raw: str) -> str:
    """MIME-заголовок -> читаемая строка. Кириллица в контуре часто в KOI8-R/CP1251."""
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


def _decode_payload(payload: bytes, charset: Optional[str]) -> str:
    """Декодирование тела с фолбэком на кодировки, встречающиеся в контуре."""
    candidates = [charset, "utf-8", "cp1251", "koi8-r"]
    for enc in candidates:
        if not enc:
            continue
        try:
            return payload.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return payload.decode("utf-8", errors="replace")


def _extract_body(msg: Message) -> tuple[str, list[str]]:
    """Возвращает (очищенный текст письма, список имён вложений).

    Чистка от шапок пересылки, цитат и дисклеймеров — в cleaner.py.
    """
    text_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[str] = []

    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue

        filename = part.get_filename()
        disposition = str(part.get("Content-Disposition") or "")
        if filename or "attachment" in disposition:
            attachments.append(_decode_mime(filename or "unnamed"))
            continue

        content_type = part.get_content_type()
        if content_type not in ("text/plain", "text/html"):
            continue

        payload = part.get_payload(decode=True)
        if not payload:
            continue

        text = _decode_payload(payload, part.get_content_charset())
        if content_type == "text/plain":
            text_parts.append(text)
        else:
            html_parts.append(text)

    body = clean_email_body(
        text_plain="\n".join(text_parts) if text_parts else None,
        text_html="\n".join(html_parts) if html_parts else None,
    )
    return body, attachments


def parse_mail(msg: Message, uid: str) -> MailItem:
    received_time = None
    date_str = msg.get("Date")
    if date_str:
        try:
            # tz-aware -> naive local, чтобы сравнения не падали
            received_time = parsedate_to_datetime(date_str)
            if received_time.tzinfo is not None:
                received_time = received_time.astimezone().replace(tzinfo=None)
        except (TypeError, ValueError):
            pass

    body, attachments = _extract_body(msg)
    
    # Парсим получателей (To + CC + BCC)
    recipients = []
    for header in ["To", "Cc", "Bcc"]:
        value = msg.get(header)
        if value:
            recipients.append(_decode_mime(value))

    return MailItem(
        uid=uid,
        sender=_decode_mime(msg.get("From", "")),
        subject=_decode_mime(msg.get("Subject", "")) or "(без темы)",
        received_time=received_time,
        message_id=msg.get("Message-ID", "").strip(),
        body=body,
        attachments=attachments,
        recipients=recipients,
    )


class MailClient:
    """IMAP-клиент. Использовать как контекстный менеджер.

    with MailClient(gmail_config()) as client:
        for item in client.fetch(limit=10):
            print(item)
    """

    def __init__(self, config: MailConfig):
        self.config = config
        self._imap: Optional[imaplib.IMAP4_SSL] = None

    def __enter__(self) -> "MailClient":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def connect(self) -> None:
        ctx = ssl.create_default_context()
        if not self.config.verify_cert:
            # Внутренний контур: self-signed CA
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        # Retry-логика: корпоративная сеть периодически блокирует SSL-соединения
        max_retries = 5
        for attempt in range(max_retries):
            try:
                self._imap = imaplib.IMAP4_SSL(
                    self.config.imap_host,
                    self.config.imap_port,
                    ssl_context=ctx,
                )
                self._imap.login(self.config.login, self.config.password)
                return
            except ConnectionResetError:
                if attempt < max_retries - 1:
                    delay = 5 * (attempt + 1)  # 5, 10, 15, 20 секунд
                    time.sleep(delay)
                else:
                    raise

    def close(self) -> None:
        if self._imap is None:
            return
        try:
            self._imap.close()
        except Exception:
            pass
        try:
            self._imap.logout()
        except Exception:
            pass
        self._imap = None

    @property
    def imap(self) -> imaplib.IMAP4_SSL:
        if self._imap is None:
            raise RuntimeError("Нет подключения. Используй `with MailClient(...)`.")
        return self._imap

    def list_folders(self) -> list[str]:
        """Имена папок в читаемом виде.

        Возвращает только имена; флаги IMAP отбрасываются.
        """
        status, data = self.imap.list()
        if status != "OK":
            return []

        folders = []
        for line in data:
            if not line:
                continue
            name = _parse_list_line(line.decode(errors="replace"))
            if name:
                folders.append(decode_imap_utf7(name))
        return folders

    def _search(self, criteria: str, literal: Optional[str] = None) -> list[str]:
        """UID SEARCH — UID стабилен между сессиями, порядковый номер нет.

        literal: не-ASCII значение (например, русское слово в теме).
        imaplib кодирует аргументы команды в ASCII, поэтому кириллицу
        приходится слать IMAP-литералом: значение кладётся в imap.literal,
        а ключ (SUBJECT/FROM) идёт последним аргументом команды.
        """
        if literal is not None:
            self.imap.literal = literal.encode("utf-8")
            status, data = self.imap.uid("SEARCH", "CHARSET", "UTF-8", criteria)
        else:
            status, data = self.imap.uid("SEARCH", None, criteria)

        if status != "OK" or not data or not data[0]:
            return []
        return data[0].decode().split()

    def fetch(
        self,
        folder: str = "INBOX",
        criteria: Optional[str] = None,
        since: Optional[datetime.timedelta] = None,
        limit: Optional[int] = 20,
        with_body: bool = True,
        literal: Optional[str] = None,
    ) -> Iterator[MailItem]:
        """Получить письма, новые первыми.

        criteria: сырой IMAP-запрос ("UNSEEN", "FROM x@y.z"). Приоритетнее since.
        since:    окно времени, напр. timedelta(days=1).
        limit:    сколько писем максимум забрать.
        literal:  не-ASCII значение для criteria (см. _search).
        """
        # Имя может быть кириллическим — сервер ждёт modified UTF-7.
        # Кавычки обязательны: в именах Gmail есть пробелы.
        encoded = encode_imap_utf7(folder)
        status, _ = self.imap.select(f'"{encoded}"', readonly=True)
        if status != "OK":
            raise RuntimeError(f"Не удалось открыть папку {folder}")

        if criteria is None:
            if since is not None:
                # IMAP SINCE — с точностью до суток, дофильтруем по времени ниже
                date = (datetime.datetime.now() - since).strftime("%d-%b-%Y")
                criteria = f'(SINCE "{date}")'
            else:
                criteria = "ALL"

        uids = self._search(criteria, literal=literal)
        if not uids:
            return

        cutoff = datetime.datetime.now() - since if since else None

        yielded = 0
        # Новые письма первыми
        for uid in reversed(uids):
            if limit is not None and yielded >= limit:
                break

            fetch_spec = "(RFC822)" if with_body else "(BODY.PEEK[HEADER])"
            status, data = self.imap.uid("FETCH", uid, fetch_spec)
            if status != "OK" or not data or not isinstance(data[0], tuple):
                continue

            item = parse_mail(email.message_from_bytes(data[0][1]), uid)

            # Не break: порядок UID не гарантирует порядок дат
            if cutoff and item.received_time and item.received_time < cutoff:
                continue

            yielded += 1
            yield item
