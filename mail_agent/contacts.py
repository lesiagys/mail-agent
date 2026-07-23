"""Управление базой контактов отправителей.

Записывает факты о контактах: имя, email, домен, даты контактов, темы писем,
количество входящих и исходящих писем. Не делает интерпретаций.
"""

import json
import os
import threading
from datetime import datetime, timedelta
from email.utils import parseaddr, getaddresses
from typing import Optional

from .client import MailItem

CONTACTS_FILE = "contacts.json"
MAX_RECENT_SUBJECTS = 5
SYNC_INTERVAL_HOURS = 1
MAX_SYNC_DAYS = 30

# Глобальный флаг для предотвращения параллельных синхронизаций
_sync_lock = threading.Lock()
_sync_in_progress = False


def is_sync_in_progress() -> bool:
    """Проверить, идет ли сейчас синхронизация."""
    return _sync_in_progress


def load_contacts() -> dict:
    """Загрузить контакты из файла."""
    if not os.path.exists(CONTACTS_FILE):
        return {"contacts": {}}
    
    with open(CONTACTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_contacts(data: dict) -> None:
    """Сохранить контакты в файл."""
    with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_domain(email: str) -> str:
    """Извлечь домен из email."""
    if "@" in email:
        return email.split("@")[1]
    return ""


def update_contacts_from_emails(
    emails: list[MailItem],
    is_incoming: bool,
    our_email: str
) -> None:
    """Обновить контакты на основе списка писем.
    
    Args:
        emails: Список писем
        is_incoming: True для входящих (INBOX), False для исходящих (Sent)
        our_email: Наш email для исключения из списка получателей
    """
    data = load_contacts()
    contacts = data.get("contacts", {})
    
    for email_item in emails:
        if is_incoming:
            # Входящее письмо: sender = контакт
            name, email_addr = parseaddr(email_item.sender)
            if not email_addr:
                continue
            
            email_addr = email_addr.lower()
            date_str = email_item.received_time.strftime("%Y-%m-%d") if email_item.received_time else datetime.now().strftime("%Y-%m-%d")
            
            if email_addr not in contacts:
                contacts[email_addr] = {
                    "name": name or "",
                    "email": email_addr,
                    "domain": extract_domain(email_addr),
                    "first_seen": date_str,
                    "last_seen": date_str,
                    "recent_subjects": [email_item.subject] if email_item.subject else [],
                    "incoming_count": 1,
                    "outgoing_count": 0,
                }
            else:
                contact = contacts[email_addr]
                # Обновляем first_seen только если дата раньше
                if date_str < contact["first_seen"]:
                    contact["first_seen"] = date_str
                # Обновляем last_seen
                if date_str > contact["last_seen"]:
                    contact["last_seen"] = date_str
                # Обновляем recent_subjects
                if email_item.subject:
                    subjects = contact.get("recent_subjects", [])
                    if email_item.subject not in subjects:
                        subjects.insert(0, email_item.subject)
                        contact["recent_subjects"] = subjects[:MAX_RECENT_SUBJECTS]
                # Инкрементируем счётчик
                contact["incoming_count"] = contact.get("incoming_count", 0) + 1
            
            # Обновляем last_sync_inbox на каждом письме
            data["last_sync_inbox"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data["contacts"] = contacts
            save_contacts(data)
        
        else:
            # Исходящее письмо: recipients = контакты
            recipients = email_item.recipients
            date_str = email_item.received_time.strftime("%Y-%m-%d") if email_item.received_time else datetime.now().strftime("%Y-%m-%d")
            
            for recipient in recipients:
                name, email_addr = parseaddr(recipient)
                if not email_addr:
                    continue
                
                email_addr = email_addr.lower()
                
                # Исключаем наш email
                if email_addr == our_email.lower():
                    continue
                
                if email_addr not in contacts:
                    contacts[email_addr] = {
                        "name": name or "",
                        "email": email_addr,
                        "domain": extract_domain(email_addr),
                        "first_seen": date_str,
                        "last_seen": date_str,
                        "recent_subjects": [email_item.subject] if email_item.subject else [],
                        "incoming_count": 0,
                        "outgoing_count": 1,
                    }
                else:
                    contact = contacts[email_addr]
                    # Обновляем first_seen только если дата раньше
                    if date_str < contact["first_seen"]:
                        contact["first_seen"] = date_str
                    # Обновляем last_seen
                    if date_str > contact["last_seen"]:
                        contact["last_seen"] = date_str
                    # Обновляем recent_subjects
                    if email_item.subject:
                        subjects = contact.get("recent_subjects", [])
                        if email_item.subject not in subjects:
                            subjects.insert(0, email_item.subject)
                            contact["recent_subjects"] = subjects[:MAX_RECENT_SUBJECTS]
                    # Инкрементируем счётчик
                    contact["outgoing_count"] = contact.get("outgoing_count", 0) + 1
                
                # Обновляем last_sync_sent на каждом письме
                data["last_sync_sent"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                data["contacts"] = contacts
                save_contacts(data)


def needs_sync() -> tuple[bool, bool, Optional[datetime], Optional[datetime]]:
    """Проверить, нужна ли синхронизация.
    
    Returns:
        (нужна_синхронизация_inbox, нужна_синхронизация_sent, 
         дата_начала_синхронизации_inbox, дата_начала_синхронизации_sent)
    """
    data = load_contacts()
    
    # Проверяем INBOX
    last_sync_inbox_str = data.get("last_sync_inbox")
    needs_inbox = False
    sync_from_inbox = None
    
    if not last_sync_inbox_str:
        # Первая синхронизация — за последний месяц
        sync_from_inbox = datetime.now() - timedelta(days=MAX_SYNC_DAYS)
        needs_inbox = True
    else:
        last_sync_inbox = datetime.strptime(last_sync_inbox_str, "%Y-%m-%d %H:%M:%S")
        hours_passed = (datetime.now() - last_sync_inbox).total_seconds() / 3600
        
        if hours_passed >= SYNC_INTERVAL_HOURS:
            # Синхронизация с last_sync, но не старше месяца
            sync_from_inbox = max(last_sync_inbox, datetime.now() - timedelta(days=MAX_SYNC_DAYS))
            needs_inbox = True
    
    # Проверяем Sent
    last_sync_sent_str = data.get("last_sync_sent")
    needs_sent = False
    sync_from_sent = None
    
    if not last_sync_sent_str:
        # Первая синхронизация — за последний месяц
        sync_from_sent = datetime.now() - timedelta(days=MAX_SYNC_DAYS)
        needs_sent = True
    else:
        last_sync_sent = datetime.strptime(last_sync_sent_str, "%Y-%m-%d %H:%M:%S")
        hours_passed = (datetime.now() - last_sync_sent).total_seconds() / 3600
        
        if hours_passed >= SYNC_INTERVAL_HOURS:
            # Синхронизация с last_sync, но не старше месяца
            sync_from_sent = max(last_sync_sent, datetime.now() - timedelta(days=MAX_SYNC_DAYS))
            needs_sent = True
    
    return needs_inbox, needs_sent, sync_from_inbox, sync_from_sent


def start_background_sync(client_factory, our_email: str) -> None:
    """Запустить фоновую синхронизацию, если нужно.
    
    Args:
        client_factory: Функция, возвращающая MailClient
        our_email: Наш email
    """
    global _sync_in_progress

    print(f"[DEBUG] Sync in progress: {_sync_in_progress}")
    
    if _sync_in_progress:
        return
    
    needs_inbox, needs_sent, sync_from_inbox, sync_from_sent = needs_sync()

    print(f"[DEBUG] Need sync INBOX: {needs_inbox}; need sync SENT: {needs_sent}")
    
    if not (needs_inbox or needs_sent):
        return
    
    def sync_task():
        global _sync_in_progress
        
        with _sync_lock:
            if _sync_in_progress:
                return
            _sync_in_progress = True
        
        try:
            # Синхронизация INBOX
            if needs_inbox and sync_from_inbox:
                print("[DEBUG] Sync INBOX")
                since_delta = datetime.now() - sync_from_inbox
                with client_factory() as client:
                    for item in client.fetch(folder="INBOX", since=since_delta):
                        update_contacts_from_emails([item], is_incoming=True, our_email=our_email)
                # Обновляем timestamp даже если писем не было
                data = load_contacts()
                data["last_sync_inbox"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                save_contacts(data)
            
            # Синхронизация Sent (пробуем разные варианты имени папки)
            if needs_sent and sync_from_sent:
                print("[DEBUG] Sync INBOX, search folder")
                since_delta = datetime.now() - sync_from_sent
                sent_folders = ["Sent", "Sent Items", "[Gmail]/Sent Mail", "Отправленные"]
                with client_factory() as client:
                    folders = client.list_folders()
                    sent_folder = None
                    for folder_name in sent_folders:
                        if folder_name in folders:
                            sent_folder = folder_name
                            break
                    
                    if sent_folder:
                        print("[DEBUG] Sync INBOX, folder found")
                        for item in client.fetch(folder=sent_folder, since=since_delta):
                            update_contacts_from_emails([item], is_incoming=False, our_email=our_email)
                # Обновляем timestamp даже если писем не было
                data = load_contacts()
                data["last_sync_sent"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                save_contacts(data)
        
        finally:
            _sync_in_progress = False
    
    thread = threading.Thread(target=sync_task, daemon=True)
    thread.start()


def search_contacts(query: str) -> list[dict]:
    """Поиск контактов по имени, email или алиасам.
    
    Ищет совпадения, где запрос является подстрокой имени, email или алиаса.
    Например, запрос "ivan" найдёт:
    - ivan@example.com (содержит "ivan")
    - petrov@example.com (если есть алиас "ivan")
    - Иван Петров (содержит "ivan" в транслитерации)
    
    Args:
        query: Поисковый запрос (имя, email, алиас или фрагмент)
    
    Returns:
        Список найденных контактов
    """
    contacts = load_contacts()
    query_lower = query.lower()
    results = []
    
    for email, contact in contacts.get("contacts", {}).items():
        name = contact.get("name", "").lower()
        email_addr = contact.get("email", "").lower()
        aliases = [a.lower() for a in contact.get("aliases", [])]
        
        # Проверяем, содержится ли запрос в имени, email или алиасах
        if (query_lower in name or 
            query_lower in email_addr or 
            any(query_lower in alias for alias in aliases)):
            results.append(contact)
    
    return results


def add_alias(email: str, alias: str) -> bool:
    """Добавить алиас к контакту.
    
    Args:
        email: Email контакта
        alias: Алиас (прозвище), которое пользователь использует
    
    Returns:
        True если алиас добавлен, False если контакт не найден
    """
    data = load_contacts()
    contacts = data.get("contacts", {})
    
    if email not in contacts:
        return False
    
    contact = contacts[email]
    aliases = contact.get("aliases", [])
    
    # Добавляем алиас, если его еще нет
    if alias not in aliases:
        aliases.append(alias)
        contact["aliases"] = aliases
        save_contacts(data)
    
    return True
