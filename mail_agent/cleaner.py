"""Очистка текста писем от служебных блоков.

Отличие от EMLMessageCleaner в b2c_daily_researcher_qwen: там при встрече
маркера цитаты цикл делает break и всё дальнейшее отбрасывается. Письма
внутреннего контура начинаются со служебной шапки Outlook, поэтому такой
подход обнуляет их целиком. Здесь служебные блоки вырезаются, а текст
вокруг них сохраняется.
"""

import re
from typing import Optional

# Предупреждение контура о внешнем отправителе НЕ вырезаем: это сигнал
# безопасности, агент должен его видеть. HTML разносит его по тегам, поэтому
# склеиваем в одну строку — иначе оно рассыпается на "⚠" / "Внешний" /
# "отправитель" и читается как мусор.
_EXTERNAL_WARNING = re.compile(
    r"[⚠!]*\s*Внешний\s+отправитель\s*"
    r"(Подозрительное\s+письмо\??\s*(Перешлите\s+на\s+)?(\S+@\S+)?)?",
    re.IGNORECASE,
)
_EXTERNAL_WARNING_TEXT = "[Предупреждение: внешний отправитель]"

# Юридический дисклеймер: от заголовка до конца письма
_DISCLAIMER_START = re.compile(
    r"(УВЕДОМЛЕНИЕ\s+О\s+КОНФИДЕНЦИАЛЬНОСТИ"
    r"|CONFIDENTIALITY\s+NOTICE"
    r"|Данное\s+сообщение.*содержит\s+конфиденциальную)",
    re.IGNORECASE,
)

# Строки шапки пересылки Outlook
_HEADER_LINE = re.compile(
    r"^\s*(От|From|Кому|To|Копия|Cc|Отправлено|Sent|Дата|Date|Тема|Subject)\s*:",
    re.IGNORECASE,
)

# Разделители блоков цитирования
_SEPARATOR = re.compile(r"^\s*([_—–-]{10,}|={10,}|\*{10,})\s*$")

# Строки-цитаты
_QUOTE_LINE = re.compile(r"^\s*>")

# "15 июля 2026 г., в 11:32, Иванов И.И. <x@y.ru> написал(а):"
_QUOTE_INTRO = re.compile(
    r"(написал\(а\)\s*:|написал\s*:|пишет\s*:|wrote\s*:"
    r"|-{2,}\s*(Исходное сообщение|Original Message|Пересланное сообщение"
    r"|Forwarded message)\s*-{2,})",
    re.IGNORECASE,
)

_URL = re.compile(r"<?https?://\S+>?")
_IMAGE_PLACEHOLDER = re.compile(r"\[(image|cid|изображение)\s*:[^\]]*\]", re.IGNORECASE)
# Невидимые распорки из HTML-вёрстки рассылок: braille blank, zero-width,
# soft hyphen и т.п. В превью съедают сотни символов, не неся смысла.
_INVISIBLE = re.compile(
    "[⠀​‌‍\u200E\u200F­⁠﻿᠎]+"
)

_MULTI_BLANK = re.compile(r"\n{3,}")
_MULTI_SPACE = re.compile(r"[ \t  ]+")


def strip_html(html: str) -> str:
    """HTML -> текст. Цитаты и служебные блоки снимаются на уровне разметки."""
    if not html or not html.strip():
        return ""

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "title", "meta", "head"]):
            tag.decompose()

        # Стандартное цитирование
        for tag in soup.find_all("blockquote"):
            tag.decompose()

        # Outlook помечает цитируемый блок id="divRplyFwdMsg"
        for tag in soup.find_all(id=re.compile(r"[Rr]ply|[Ff]wd|divRplyFwdMsg")):
            tag.decompose()

        for tag in soup.find_all(class_=re.compile(r"[Qq]uote|EmailQuote|gmail_quote")):
            tag.decompose()

        # Вертикальная черта слева — типичная разметка цитаты
        for tag in soup.find_all(style=re.compile(r"border-left")):
            tag.decompose()

        # separator=" " + strip=True склеивает слова, разнесённые по тегам:
        # иначе "Внешний отправитель" приходит тремя строками и построчные
        # паттерны по нему не срабатывают. Блочные теги переносим вручную.
        for tag in soup.find_all(["p", "div", "br", "tr", "li", "h1", "h2", "h3"]):
            tag.append(soup.new_string("\n"))
        text = soup.get_text(separator=" ")
    except ImportError:
        text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
        text = re.sub(r"</(p|div|tr)>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)

    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    text = re.sub(r"&#\d+;", " ", text)
    return text


def clean_text(text: str, keep_urls: bool = False) -> str:
    """Убрать служебные блоки, сохранив содержательный текст.

    keep_urls: оставить ссылки. По умолчанию вырезаются — в превью они
    занимают место, не добавляя смысла.
    """
    if not text:
        return ""

    # Убираем распорки до разбора: иначе строка из них выглядит непустой
    text = _INVISIBLE.sub("", text)

    # Дисклеймер идёт до конца письма — обрезаем по нему
    match = _DISCLAIMER_START.search(text)
    if match:
        text = text[: match.start()]

    # Схлопываем предупреждение о внешнем отправителе, пока текст цельный:
    # после разбиения на строки его части уже не собрать
    flat = _MULTI_SPACE.sub(" ", text.replace("\n", " ").replace(" ", " "))
    has_external_warning = bool(_EXTERNAL_WARNING.search(flat))
    if has_external_warning:
        text = _EXTERNAL_WARNING.sub(" ", text)

    result: list[str] = []
    for raw in text.split("\n"):
        line = _MULTI_SPACE.sub(" ", raw.replace(" ", " ")).strip()

        if not line:
            # Пустые схлопываем позже, но абзацы сохраняем
            if result and result[-1] != "":
                result.append("")
            continue

        if _SEPARATOR.match(line):
            continue
        if _HEADER_LINE.match(line):
            continue
        if _QUOTE_LINE.match(line):
            continue
        if _QUOTE_INTRO.search(line):
            continue

        if not keep_urls:
            line = _URL.sub("", line)
        line = _IMAGE_PLACEHOLDER.sub("", line)
        line = _MULTI_SPACE.sub(" ", line).strip()

        # Строка могла состоять только из ссылки или плейсхолдера
        if line:
            result.append(line)

    cleaned = "\n".join(result)
    cleaned = _MULTI_BLANK.sub("\n\n", cleaned)
    cleaned = cleaned.strip()

    # Предупреждение возвращаем первой строкой — так оно видно агенту
    # и не занимает место рассыпанными обрывками
    if has_external_warning:
        cleaned = f"{_EXTERNAL_WARNING_TEXT}\n{cleaned}" if cleaned else _EXTERNAL_WARNING_TEXT

    return cleaned


def clean_email_body(
    text_plain: Optional[str] = None,
    text_html: Optional[str] = None,
    keep_urls: bool = False,
) -> str:
    """Получить осмысленный текст письма.

    Предпочитаем text/plain. Если после чистки он пуст, а HTML-версия
    что-то даёт — берём её.
    """
    if text_plain:
        cleaned = clean_text(text_plain, keep_urls=keep_urls)
        if cleaned:
            return cleaned

    if text_html:
        return clean_text(strip_html(text_html), keep_urls=keep_urls)

    return ""
