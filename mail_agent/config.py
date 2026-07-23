"""Конфигурация почтовых провайдеров.

Единственное место, где Gmail и внутренний контур отличаются.
Код получения писем от провайдера не зависит.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class MailConfig:
    imap_host: str
    login: str
    password: str
    imap_port: int = 993
    # Внутренний контур ходит через self-signed сертификаты
    verify_cert: bool = True

    # SMTP для отправки. Пусто — отправка недоступна.
    smtp_host: str = ""
    smtp_port: int = 587
    # Адрес в поле From. Пусто — берётся login.
    smtp_from: str = ""
    # Логин к SMTP, если отличается от IMAP (в контуре — с доменом)
    smtp_login: str = ""

    @property
    def sender_address(self) -> str:
        return self.smtp_from or self.login

    def __post_init__(self):
        if not self.login or not self.password:
            raise ValueError(
                f"Не заданы логин/пароль для {self.imap_host}. "
                "Проверь .env"
            )


def gmail_config() -> MailConfig:
    """Gmail для локального теста.

    Пароль — App Password (16 строчных букв), не пароль от аккаунта:
    https://myaccount.google.com/apppasswords
    """
    # Google показывает пароль как "abcd efgh ijkl mnop" — пробелы не значимы
    password = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")

    if password and (len(password) != 16 or not password.isalpha()):
        raise ValueError(
            f"GMAIL_APP_PASSWORD не похож на App Password "
            f"(получено {len(password)} символов, ожидается 16 букв).\n"
            "Вход по обычному паролю аккаунта Google отключён с 2022 года.\n"
            "Сгенерируй App Password: https://myaccount.google.com/apppasswords"
        )

    return MailConfig(
        imap_host="imap.gmail.com",
        login=os.getenv("GMAIL_LOGIN", ""),
        password=password,
        smtp_host="smtp.gmail.com",
        smtp_port=465,
    )


def sber_config() -> MailConfig:
    """Внутренний контур. Хост и схема логина — как в b2c_daily_researcher_qwen."""
    login = os.getenv("D_LOGIN", "")
    domain = os.getenv("SBER_MAIL_DOMAIN", "omega.sbrf.ru")
    return MailConfig(
        imap_host=os.getenv("SBER_IMAP_HOST", "imap.sberbank.ru"),
        login=login,
        password=os.getenv("MAIL_PASS", ""),
        smtp_host=os.getenv("SBER_SMTP_HOST", "smtp.sberbank.ru"),
        smtp_port=int(os.getenv("SBER_SMTP_PORT", "587")),
        # В контуре SMTP-логин идёт с доменом, IMAP — без
        smtp_login=f"{login}@{domain}" if login else "",
        smtp_from=os.getenv("SBER_SMTP_FROM", ""),
    )


def get_config(provider: str | None = None) -> MailConfig:
    provider = provider or os.getenv("MAIL_PROVIDER", "gmail")
    if provider == "gmail":
        return gmail_config()
    if provider == "sber":
        return sber_config()
    raise ValueError(f"Неизвестный провайдер: {provider}")
