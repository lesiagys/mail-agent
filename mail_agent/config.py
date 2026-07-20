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
    )


def sber_config() -> MailConfig:
    """Внутренний контур. Хост и схема логина — как в b2c_daily_researcher_qwen."""
    login = os.getenv("D_LOGIN", "")
    return MailConfig(
        imap_host=os.getenv("SBER_IMAP_HOST", "imap.sberbank.ru"),
        # В контуре логин к SMTP шёл как {login}@omega.sbrf.ru
        login=login,
        password=os.getenv("MAIL_PASS", ""),
    )


def get_config(provider: str | None = None) -> MailConfig:
    provider = provider or os.getenv("MAIL_PROVIDER", "gmail")
    if provider == "gmail":
        return gmail_config()
    if provider == "sber":
        return sber_config()
    raise ValueError(f"Неизвестный провайдер: {provider}")
