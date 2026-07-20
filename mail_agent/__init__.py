from .client import MailClient, MailItem, parse_mail
from .config import MailConfig, get_config, gmail_config, sber_config

__all__ = [
    "MailClient",
    "MailItem",
    "parse_mail",
    "MailConfig",
    "get_config",
    "gmail_config",
    "sber_config",
]
