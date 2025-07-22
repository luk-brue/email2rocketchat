import csv
import os
from dotenv import load_dotenv
import re
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
import requests
from exchangelib import Credentials, Account, DELEGATE, Message
import quopri
import re
from bs4 import BeautifulSoup
from pprint import pprint, pformat
from rocketchat_API.rocketchat import RocketChat
import traceback



"""
Dieses Skript kann auf ein Outlook Gruppenpostfach zugreifen und dort Typo3-Kontaktfor-
mular-Anfragen aus dem Posteingang extrahieren. Dann kann das in RocketChat als Message gepostet werden,
Das passiert über eine API. Zwischendurch werden die Mails erst mal sortiert in Typo3-versendet
und normale Mails. Dann wird auch getrackt, welche Mails bereits als Aufgaben über die API
hochgeladen wurden, damit sich nichts doppelt. Das passiert über eine CSV-Datei, die im 
gleichen Ordner wie dieses Skript erstellt wird. 
Ein weiterer Teil des Skripts befasst sich damit, den Inhalt der Mail zu parsen,
wobei nur die HTML-Tabelle mit den Daten aus dem Kontaktformular extrahiert wird, da sich
sonst der Inhalt doppelt - einmal als Text, einmal als Tabelle.  
Außerdem wird das Empfangsdatum extrahiert und der Name des Absenders, um die Karte in
Vikunja damit zu bestücken. 

Voraussetzung für die Funktion: Eine Person, Uni-Angehörig, muss Zugriff auf das
Gruppenpostfach haben. Außerdem braucht es einen Rocket-Chat Account mit API Zugang der in 
einem Channel Nachrichten posten darf, und den Namen des Channels.  
Die ganzen Zugangsdaten etc. werden in einer Konfigurationsdatei gespeichert, die nicht
verschlüsselt ist (so advanced bin ich noch nicht)... Die Datei muss im gleichen Ordner
liegen und heißt .env und sieht so aus:

EMAIL_ADDRESS = "psycho.methoden@uni-kassel.de"  # Exchange-Gruppen-Postfach-E-Mail-Adresse
EMAIL_PASSWORD = "xxxxxxxxxxxxxx"                # Passwort des Uni-Accounts der Person
UK_NUMMER = "uk012345"                           # nur die uk-nummer der Person mit Zugriff
RC_SERVER = https://rocketchat.uni-kassel.de
RC_PASS = passwort rocketchat
RC_USER = username rocketchat
"""

# Logging konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Konfigurationsklasse
class Config:
    def __init__(self):
        load_dotenv()
        self.uk_nummer = os.getenv("UK_NUMMER")
        self.email_address = os.getenv("EMAIL_ADDRESS")
        self.email_password = os.getenv("EMAIL_PASSWORD")
        self.rc_pass = os.getenv("RC_PASS")
        self.rc_server = os.getenv("RC_SERVER", "").rstrip('/')
        self.rc_user = os.getenv("RC_USER")
        self.processed_file = 'processed_emails.csv'
        self.rc_channel = os.getenv("RC_CHANNEL")

def init_exchange_connection(config: Config) -> Account:
    """Initialisiert die Verbindung zu Exchange."""
    try:
        credentials = Credentials(username=config.uk_nummer, password=config.email_password)
        account = Account(primary_smtp_address=config.email_address,
                             credentials=credentials,
                             autodiscover=True,
                             access_type=DELEGATE)
        logger.info("Exchange-Verbindung erfolgreich hergestellt")
        return account
    except Exception as e:
        logger.error(f"Fehler beim Verbinden mit Exchange: {e}")
        raise

def rocket_chat_login(config: Config) -> RocketChat:
    try:
        logger.info("Initialisiere Rocket-Chat-API Zugriff")
        rocket = RocketChat(config.rc_user, config.rc_pass, server_url=config.rc_server)
        logger.info("RocketChat API Login erfolgreich")
        return rocket
    except Exception as e:
        logger.error(f"Fehler beim Verbinden mit RocketChat API: {e}")
        raise

def load_processed_emails(filename: str) -> Set[str]:
    """Lädt bereits verarbeitete E-Mail-IDs aus der CSV-Datei."""
    processed = set()
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    processed.add(row['message_id'])
                logger.info(f"{len(processed)} bereits verarbeitete E-Mails geladen")
        except Exception as e:
            logger.error(f"Fehler beim Laden der verarbeiteten E-Mails: {e}")
    return processed

def create_processed_email_record(message_id: str, subject: str, sender: str, vikunja_task_id: Optional[int] = None) -> Dict:
    """Erstellt einen Datensatz für eine verarbeitete E-Mail."""
    return {
        'message_id': message_id,
        'subject': subject,
        'sender': sender,
        'processed_at': datetime.now().isoformat(),
        'vikunja_task_id': vikunja_task_id or ''
    }

def save_processed_email_records(filename: str, records: List[Dict]):
    """Speichert eine Liste von E-Mail-Datensätzen in einer CSV-Datei."""
    file_exists = os.path.exists(filename)
    try:
        with open(filename, 'a', newline='', encoding='utf-8') as file:
            fieldnames = ['message_id', 'subject', 'sender', 'processed_at', 'vikunja_task_id']
            writer = csv.DictWriter(file, fieldnames=fieldnames)

            if not file_exists:
                writer.writeheader()

            writer.writerows(records)  # Mehrere Datensätze schreiben

        logger.info(f"{len(records)} E-Mails als verarbeitet markiert")
    except Exception as e:
        logger.error(f"Fehler beim Speichern der verarbeiteten E-Mails: {e}")

def check_typo3_x_mailer(message: Message) -> Optional[str]:
    """Prüft, ob ein TYPO3 X-Mailer Header vorhanden ist und gibt den Wert zurück."""
    if not hasattr(message, 'headers') or not message.headers:
        logger.info("❌ Keine Headers verfügbar")
        return None

    for header in message.headers:
        if hasattr(header, 'name') and hasattr(header, 'value') and header.name.lower() == 'x-mailer':
            logger.info(f"✅ X-Mailer gefunden: '{header.value}'")
            return header.value

    logger.info("❌ Kein X-Mailer Header gefunden")
    return None

def is_typo3_contact_form(message: Message) -> bool:
    """Prüft, ob es sich um eine TYPO3-Kontaktformular-E-Mail handelt."""
    logger.info("🔍 Starte TYPO3-Kontaktformular-Prüfung...")

    # Prüfung auf TYPO3 X-Mailer Header
    x_mailer_value = check_typo3_x_mailer(message)
    if not x_mailer_value == 'TYPO3':
        return False

    # Prüfung, dass es sich NICHT um eine Antwort handelt
    subject = message.subject or ""
    reply_prefixes = ['AW:', 'RE:', 'Aw:', 'Re:', 'aw:', 're:']
    if any(subject.strip().startswith(prefix) for prefix in reply_prefixes):
        logger.info(f"❌ Subject hat Antwort-Präfix: '{subject}'")
        return False

    # Prüfung auf References oder In-Reply-To Header (deutet auf Antwort hin)
    if hasattr(message, 'headers') and message.headers:
        for header in message.headers:
            if hasattr(header, 'name') and hasattr(header, 'value'):
                header_name = header.name.lower()
                if header_name in ['references', 'in-reply-to']:
                    logger.info(f"❌ {header.name} Header gefunden")
                    return False

    # Alle verfügbaren Body-Inhalte sammeln
    all_body_content = ""
    for body_attr in ['html_body', 'text_body', 'body']:
        if hasattr(message, body_attr):
            body = getattr(message, body_attr)
            if body:
                body_str = str(body)
                all_body_content += body_str + "\n"
                logger.info(f"✅ {body_attr} gefunden (Länge: {len(body_str)})")

    if not all_body_content:
        logger.info("❌ Kein Body-Inhalt verfügbar")
        return False

    # Prüfung auf TYPO3-Kontaktformular-Kennzeichen
    if 'powermail_all' in all_body_content:
        logger.info("🎯 'powermail_all' gefunden - TYPO3 Kontaktformular erkannt!")
        return True

    typo3_indicators = [
        'Name, Vorname',
        'E-Mail-Adresse',
        'Studiengang',
        'Empra/',
        'Projekt',
        'Methodenberatung',
        'Captcha'
    ]
    found_indicators = sum(1 for indicator in typo3_indicators if indicator in all_body_content)
    logger.info(f"Gefundene Indikatoren: {found_indicators}")

    if found_indicators >= 3:
        logger.info("🎯 Genug Indikatoren gefunden - TYPO3 Kontaktformular erkannt!")
        return True

    logger.info("❌ Finale Entscheidung: Nicht als TYPO3-Kontaktformular erkannt")
    return False

def parse_email_data(item: Message) -> Dict[str, str]:
    """Parst die relevanten Daten aus der TYPO3 E-Mail und extrahiert die HTML-Tabelle mit BeautifulSoup."""
    logger.info("🔍 Starte E-Mail-Parsing (HTML-Tabelle mit BeautifulSoup)...")

    # E-Mail-Datum extrahieren
    email_date = None
    if hasattr(item, 'datetime_received') and item.datetime_received:
        email_date = item.datetime_received.isoformat()
        logger.info(f"📅 E-Mail-Datum gefunden: {email_date}")
    elif hasattr(item, 'datetime_sent') and item.datetime_sent:
        email_date = item.datetime_sent.isoformat()
        logger.info(f"📅 E-Mail-Datum (gesendet): {email_date}")
    else:
        email_date = datetime.now().isoformat()
        logger.info(f"📅 Fallback E-Mail-Datum: {email_date}")

    # Absendername extrahieren
    sender_name = item.sender.name if item.sender and item.sender.name else "Unbekannt"
    logger.info(f"👤 Absendername: {sender_name}")

    # Body extrahieren und HTML-Tabelle mit BeautifulSoup extrahieren
    table_content = ""
    if hasattr(item, 'body'):
        body = item.body
        try:
            # Quoted-printable dekodieren
            body_bytes = body.encode('utf-8')  # In Bytes kodieren
            body = quopri.decodestring(body_bytes).decode('utf-8') # in UTF-8 kodieren
            logger.info(f"✅ Body gefunden (Länge: {len(body)})")

            # BeautifulSoup verwenden, um den HTML-Code zu parsen
            soup = BeautifulSoup(body, 'html.parser')

            # Tabelle mit der Klasse "powermail_all" finden
            table = soup.find('table', class_='powermail_all')
            if table:
                table_content = str(table)  # HTML-Code der Tabelle extrahieren
                logger.info("✅ HTML-Tabelle extrahiert")
                results = {}
                # Extract (1st and 2nd columns) 
                for row in table.find_all('tr'):  
                    columns = row.find_all('td')
                    feld = columns[0].text
                    inhalt = columns[1].text
                    results[feld] = inhalt
            else:
                logger.info("❌ Keine HTML-Tabelle gefunden")
                logger.info(f"Gesamter Body-Inhalt: {body}")  # Protokolliere den gesamten Body
                results = None
        except Exception as e:
            logger.error(f"Fehler beim Verarbeiten des Body: {e}")
    else:
        logger.info("❌ Kein Body Attribut verfügbar")

    parsed_data = {
        'sender_name': sender_name,  # Nur den Namen
        #'email_content': table_content,  # Nur die HTML-Tabelle
        'subject': item.subject,
        'sender': str(item.sender) if item.sender else 'Unbekannt',
        'received_date': email_date
    }

    parsed_data.update(results) # append the html table parsed dict
    # logger.info(f"Parsed data content:{pprint(parsed_data)}")
    return parsed_data

def rc_post_message(config: Config, email_data: Dict[str, str], rocket: RocketChat) -> Optional[str]:
    """Postet eine Message in Rocket Chat"""
    logger.info("🚀 Erstelle Rocket-Chat-Nachricht...")
    # extrahiere Felder aus Dict
    fachsemester = email_data['Fachsemester '].strip()
    sender = f"{email_data['sender_name']}"  # Absendername
    art = email_data['Art der Arbeit (Empra/ WHA/ Projekt/- oder Abschlussarbeit...)\n'].strip()
    betreuung = email_data['Name der Betreuungsperson '].strip()
    studiengang = email_data['Studiengang '].strip()
    fachgebiet = email_data['Fachgebiet, dem die Betreuungsperson angehört (z.B. "Entwicklungspsychologie")\n'].strip()
    description = f"{pprint(email_data)}"
    start_date = email_data.get('received_date', datetime.now().isoformat() + 'Z')
    # poste Nachricht
    try:
        response = rocket.chat_post_message(
            room_id=config.rc_channel,
            text = f"**{sender}**\n{art} bei {betreuung} ({fachgebiet})\n{studiengang}, {fachsemester}. FS."
            )

        logger.info(f"📊 API Response Status: {response.status_code}")
        logger.info(f"📄 API Response JSON: {pprint(response.json())}")

        if response.status_code in [200, 201]:
            rc_message_id = response.json()['message']['_id']
            logger.info(f"🎯 Rocket-Chat Message erfolgreich erstellt! Message-ID: {rc_message_id}")
            return rc_message_id
        else:
            logger.error(f"❌ Fehler beim Erstellen der Rocket-Chat-Message: {response.status_code}")
            logger.error(f"📄 Response Text: {len(response.text)} Zeichen")
            return None

    except Exception as e:
        logger.error(f"❌ Unerwarteter Fehler bei der Rocket-Chat-API-Anfrage: {e}")
        logger.error(traceback.format_exc())
        return None

def rc_post_detail_thread(rocket: RocketChat, config: Config, email_data: Dict[str, str], rc_id: str) -> Optional[str]:
    beschreibung = email_data['Kurze Beschreibung des Projekts (Hypothesen, Ablauf, erhobene Variablen, Datenstruktur, geplante Analyse)\n']
    fragen = email_data['Konkreten Fragen + Eigene Lösungsansätze? ° ']
    try:
        logger.info(f"Poste Details in Thread unter Nachricht mit ID {rc_id}")
        response = rocket.chat_post_message(
            room_id=config.rc_channel,
            tmid=rc_id,
            text=f"**Beschreibung**:\n{beschreibung}\n\n**Fragen**:\n{fragen}"
        )

        logger.info(f"📊 Detail-Thread: API Response Status: {response.status_code}")
        logger.info(f"📄 Detail-Thread: API Response JSON: {pformat(response.json())}")

        if response.status_code in [200, 201]:
            logger.info(f"🎯 Rocket-Chat Detail Thread erfolgreich erstellt!")
            return response.json()['success']
        else:
            logger.error(f"❌ Fehler beim Erstellen des RocketChat Detail Threads: {response.status_code}")
            logger.error(f"📄 Response Text: {len(response.text)} Zeichen")
            return None

    except Exception as e:
        logger.error(f"❌ Unerwarteter Fehler bei dem Erstellen des RocketChat Detail Threads: {e}")
        logger.error(traceback.format_exc())
        return None

def process_email(config: Config, account: Account, message: Message, processed_emails: Set[str]):
    """Verarbeitet eine einzelne E-Mail."""
    message_id = message.message_id
    subject = message.subject or "Kein Subject"

    logger.info(f"\n=== Verarbeite E-Mail ===")
    logger.info(f"Message ID: {message_id}")
    logger.info(f"Subject: {subject}")
    logger.info(f"Sender: {message.sender}")

    if message_id in processed_emails:
        logger.info(f"❌ Überspringe - bereits verarbeitet")
        return None, False

    logger.info(f"✅ Neue E-Mail - führe TYPO3-Prüfung durch...")

    if not is_typo3_contact_form(message):
        logger.info(f"❌ Nicht als TYPO3-Kontaktformular erkannt")
        return None, False

    logger.info(f"🎯 TYPO3-Kontaktformular gefunden: {subject}")

    email_data = parse_email_data(message)
    rocket = rocket_chat_login(config)
    rc_id = rc_post_message(config, email_data, rocket = rocket)
    rc_post_detail_thread(config = config, rocket = rocket, email_data = email_data, rc_id = rc_id)
    return rc_id, True

def process_emails(config: Config, account: Account, max_emails: int = 50):
    """Verarbeitet neue E-Mails aus dem Postfach."""
    try:
        inbox = account.inbox
        messages = list(inbox.all().order_by('-datetime_received')[:max_emails])
        logger.info(f"Überprüfe {len(messages)} E-Mails...")

        processed_emails = load_processed_emails(config.processed_file)
        processed_records = []

        for message in messages:
            try:
                task_id, processed = process_email(config, account, message, processed_emails)
                if processed:
                    processed_records.append(create_processed_email_record(
                        message.message_id,
                        message.subject or '',
                        str(message.sender) if message.sender else '',
                        task_id
                    ))
            except Exception as e:
                logger.error(f"Fehler beim Verarbeiten der E-Mail {message.message_id}: {e}")
                import traceback
                logger.error(traceback.format_exc())

        save_processed_email_records(config.processed_file, processed_records)
        logger.info(f"Verarbeitung abgeschlossen: {len(processed_records)} neue Aufgaben erstellt")

    except Exception as e:
        logger.error(f"Fehler beim Verarbeiten der E-Mails: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise

def main():
    """Hauptfunktion."""
    config = Config()

    try:
        account = init_exchange_connection(config)
        process_emails(config, account, max_emails=100)
    except Exception as e:
        logger.error(f"Fehler in der Hauptfunktion: {e}")

if __name__ == "__main__":
    main()