#!/usr/bin/env python3
"""Получить список писем.

    python check_mail.py                      # Gmail, последние 20
    python check_mail.py --since 1d --limit 5
    python check_mail.py --provider sber --folders
"""

import argparse
import datetime
import sys

from mail_agent import MailClient, get_config


def parse_since(value: str) -> datetime.timedelta:
    unit = value[-1]
    amount = int(value[:-1])
    if unit == "d":
        return datetime.timedelta(days=amount)
    if unit == "h":
        return datetime.timedelta(hours=amount)
    raise argparse.ArgumentTypeError("Формат: 3d или 12h")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["gmail", "sber"], default=None)
    parser.add_argument("--folder", default="INBOX")
    parser.add_argument("--since", type=parse_since, default=None)
    parser.add_argument("--criteria", default=None, help='напр. "UNSEEN"')
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--folders", action="store_true", help="показать папки и выйти")
    parser.add_argument("--body", action="store_true", help="печатать текст письма")
    args = parser.parse_args()

    try:
        config = get_config(args.provider)
    except ValueError as e:
        print(f"Ошибка конфигурации: {e}", file=sys.stderr)
        return 1

    print(f"Подключаюсь к {config.imap_host} как {config.login}...")

    try:
        with MailClient(config) as client:
            if args.folders:
                for folder in client.list_folders():
                    print(folder)
                return 0

            items = list(
                client.fetch(
                    folder=args.folder,
                    criteria=args.criteria,
                    since=args.since,
                    limit=args.limit,
                    with_body=args.body,
                )
            )

            if not items:
                print("Писем не найдено.")
                return 0

            print(f"\nНайдено писем: {len(items)}\n")
            for i, item in enumerate(items, 1):
                ts = (
                    item.received_time.strftime("%Y-%m-%d %H:%M")
                    if item.received_time
                    else "?"
                )
                print(f"{i:>3}. [{ts}] {item.sender}")
                print(f"     {item.subject}")
                if item.attachments:
                    print(f"     вложения: {', '.join(item.attachments)}")
                if args.body and item.body:
                    preview = item.body[:300].replace("\n", " ")
                    print(f"     {preview}...")
                print()

    except Exception as e:
        print(f"Ошибка: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
