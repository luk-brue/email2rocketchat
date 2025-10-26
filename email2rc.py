import csv
import os
from stats_table_manager import StatsTableManager, glimpse # custom class
from dotenv import load_dotenv
import re
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
import requests
from exchangelib import Configuration, Credentials, Account, DELEGATE, Message
from exchangelib.services import SubscribeToStreaming, SyncFolderItems
from exchangelib.properties import NewMailEvent
import quopri
import re
from bs4 import BeautifulSoup
from pprint import pprint, pformat
from rocketchat_API.rocketchat import RocketChat
import traceback
import json
import pandas as pd



"""
Das Skript kann auf ein Outlook Gruppenpostfach zugreifen und dort Typo3-Kontaktfor-
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
    """Initialisiert die Verbindung zu Exchange. Sollten hier mit der Konfigurations jemals
     Fehler auftreten, in account() autodiscover auf True setzen und
     config wegnehmen und dafür credentials hineintun. 
     Autodiscover ist nur aus um Ressourcen zu sparen"""
    try:
        credentials = Credentials(username=config.uk_nummer, password=config.email_password)
        exconfig = Configuration(credentials = credentials,
                                service_endpoint='https://mail.uni-kassel.de/EWS/Exchange.asmx',
                                auth_type='NTLM',
                                max_connections=2)
        account = Account(primary_smtp_address=config.email_address,
                             config=exconfig,
                             autodiscover=False,
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
                logger.info(f"{len(processed)} Einträge in processed_emails.csv enthalten")
        except Exception as e:
            logger.error(f"Fehler beim Laden der processed_emails.csv: {e}")
    return processed

def save_processed_email(filename: str, message_id):
    file_exists = os.path.exists(filename)
    try:
        with open(filename, 'a', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=['message_id'])
            # Create file + header if it does not exist
            if not file_exists:
                writer.writeheader()
                logger.info("Erstelle CSV-Datei.")
            # Check if the file is empty and create header if necessary
            if file.tell() == 0:
                writer.writeheader()
                logger.info("Leere CSV-Datei - erstelle Header")
            writer.writerow({'message_id': message_id})

        logger.info("Eintrag in processed_emails.csv gesetzt.")
    except Exception as e:
        logger.error(f"Fehler beim Speichern in processed_emails.csv: {e}")

def clean_up_processed_file(filename: str, messages: list, processed_emails: Set[str]):
    """Routine to prevent the csv file to grow larger and larger: Restrict the possible IDs that the file may
    contain to those who are present in the INBOX. 
    :param filename: The name, defined in Config (processed_emails.csv)
    :param messages: A list of exchangelib Message objects, each having a message_id attribute
    :param processed_emails: The result of reading the csv file with load_processed_emails()
    """
    logger.info("Finde obsolete Message-IDs in csv-Datei...")
    message_ids = set()
    file_exists = os.path.exists(filename)
    for message in messages:
        try:
            message_ids.add(message.message_id)
        except Exception as e:
            logger.error(e)
    #logger.info(pformat(message_ids))
    obsolete_ids = processed_emails - message_ids # calculate set difference
    processed_emails.difference_update(obsolete_ids) # update the set to contain in-obsolete ids
    try:
        with open(filename, 'w', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=['message_id'])
            if not file_exists:
                logger.info("CSV-Datei erstellt.")
                writer.writeheader()
            # Check if the file is empty and create header if necessary
            if file.tell() == 0:
                writer.writeheader()
                logger.info("Leere CSV-Datei - erstelle Header")
            writer.writerows([{'message_id': mid} for mid in processed_emails])
        logger.info(f"{len(obsolete_ids)} obsolete Message-IDs entfernt aus CSV-Datei.")
        return processed_emails
    except Exception as e:
        logger.error(f"Fehler beim Speichern in CSV-Datei: {e}")
        return None

def check_typo3_x_mailer(message: Message) -> Optional[str]:
    """Prüft, ob ein TYPO3 X-Mailer Header vorhanden ist und gibt den Wert zurück."""
    if not hasattr(message, 'headers') or not message.headers:
        logger.info("Keine Headers verfügbar")
        return None

    for header in message.headers:
        if hasattr(header, 'name') and hasattr(header, 'value') and header.name.lower() == 'x-mailer':
            logger.info(f"✅ X-Mailer gefunden: '{header.value}'")
            return header.value

    logger.info("Kein X-Mailer Header gefunden")
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
        logger.info(f"Subject hat Antwort-Präfix: '{subject}'")
        return False

    # Prüfung auf References oder In-Reply-To Header (deutet auf Antwort hin)
    if hasattr(message, 'headers') and message.headers:
        for header in message.headers:
            if hasattr(header, 'name') and hasattr(header, 'value'):
                header_name = header.name.lower()
                if header_name in ['references', 'in-reply-to']:
                    logger.info(f"{header.name} Header gefunden")
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
        logger.info("Kein Body-Inhalt verfügbar")
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

    logger.info("Finale Entscheidung: Nicht als TYPO3-Kontaktformular erkannt")
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
        email_date = datetime.now().isoformat() + 'Z'
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
                logger.info("Keine HTML-Tabelle gefunden")
                logger.info(f"Gesamter Body-Inhalt: {body}")  # Protokolliere den gesamten Body
                results = None
        except Exception as e:
            logger.error(f"Fehler beim Verarbeiten des Body: {e}")
    else:
        logger.info("Kein Body Attribut verfügbar")
    
    try: # Optionales Feld
        betreuung = results['Name der Betreuungsperson '].strip()
    except KeyError:
        betreuung = "..."
    try: # optionales Feld.
        rskript = results['Bei R Fragen: R Skript (bitte Code einfach in das Feld kopieren)\n']
        rskript = '\n'.join(rskript.splitlines()) # remove \r\n (Windows type Line Endings) and replace with \n
    except KeyError:
        rskript = None
    
    beschreibung = results['Kurze Beschreibung des Projekts (Hypothesen, Ablauf, erhobene Variablen, Datenstruktur, geplante Analyse)\n']
    beschreibung = beschreibung.replace("*", "∗") # multiplication star should not be interpreted as markdown
    beschreibung = beschreibung.replace(">", "›") # > erzeugt Zitat-Blöcke, › nicht
    fragen = results['Konkreten Fragen + Eigene Lösungsansätze? ° ']
    fragen = fragen.replace("*", "∗") 
    fragen = fragen.replace(">", "›")

    parsed_data = {
        'sender_name': sender_name,  # Nur den Namen
        #'email_content': table_content,  # Nur die HTML-Tabelle
        'subject': item.subject,
        'sender': str(item.sender) if item.sender else 'Unbekannt',
        'received_date': email_date,
        'message_id': item.message_id,
        'fachsemester': results['Fachsemester '].strip(),
        'art': results['Art der Arbeit (Empra/ WHA/ Projekt/- oder Abschlussarbeit...)\n'].strip(),
        'betreuung': betreuung,
        'studiengang': results['Studiengang '].strip(),
        'fachgebiet': results['Fachgebiet, dem die Betreuungsperson angehört (z.B. "Entwicklungspsychologie")\n'].strip(),
        'beschreibung': beschreibung,
        'fragen': fragen,
        'rskript': rskript
    }

    #parsed_data.update(results) # append the html table parsed dict
    #logger.info(f"Parsed data content:{pformat(parsed_data)}")
    return parsed_data

def rc_post_message(config: Config, email_data: Dict[str, str], rocket: RocketChat) -> Optional[str]:
    """Postet eine Message in Rocket Chat"""
    logger.info("🚀 Erstelle Rocket-Chat-Nachricht...")
    # extrahiere Felder aus Dict
    fachsemester = f"{email_data['fachsemester']}"
    sender = f"{email_data['sender_name']}"  # Absendername
    art = f"{email_data['art']}"
    betreuung = f"{email_data['betreuung']}"
    studiengang = f"{email_data['studiengang']}"
    fachgebiet = f"{email_data['fachgebiet']}"
    #description = f"{pprint(email_data)}"
    start_date = f"{email_data['received_date']}"
    # poste Nachricht
    try:
        response = rocket.chat_post_message(
            room_id=config.rc_channel,
            text = f"**{sender}**\n{art} bei {betreuung} ({fachgebiet})\n{studiengang}, {fachsemester}. FS."
            )

        logger.info(f"📊 API Response Status: {response.status_code}")
        #logger.info(f"📄 API Response JSON: {pprint(response.json())}")

        if response.status_code in [200, 201]:
            rc_message_id = response.json()['message']['_id']
            logger.info(f"🎯 Rocket-Chat Message erfolgreich erstellt! Message-ID: {rc_message_id}")
            return rc_message_id
        else:
            logger.error(f"❌ Fehler beim Erstellen der Rocket-Chat-Message: {response.status_code}")
            logger.error(f"📄 Response Text: {pformat(response.text)}")
            return None
    except Exception as e:
        logger.error(f"❌ Unerwarteter Fehler bei der Rocket-Chat-API-Anfrage: {e}")
        logger.error(traceback.format_exc())
        return None

def rc_post_detail_thread(rocket: RocketChat, config: Config, email_data: Dict[str, str], rc_id: str) -> Optional[str]:
    beschreibung = email_data['beschreibung']
    fragen = email_data['fragen']
    rskript = email_data['rskript']
    try:
        logger.info(f"🚀 Poste Details in Thread unter Nachricht mit ID {rc_id}")
        detailtext=f"**Beschreibung**:\n{beschreibung}\n\n**Fragen**:\n{fragen}\n\n**R-Skript**:\n```r\n{rskript}\n```"
        msg_len = len(detailtext)
        if msg_len <= 5000:
            croppedtext = detailtext
        elif rskript == None: # Don't add closing backticks if Rscript is not there
            croppedtext = detailtext[:4975] + f"\n[...] {msg_len - 4994} weitere Zeichen"
        else: # Do add closing backticks if Rscript exists
            croppedtext = detailtext[:4965] + f"\n[...] {msg_len - 4994} weitere Zeichen\n```"
        # RocketChat hat default die Einstellung Message_MaxAllowedSize auf 5000 Zeichen
        # Alles über 5000 Zeichen wird abgeschnitten, damit die Nachricht gepostet werden kann. 
        #croppedtext=(detailtext[:4959] + '\n\n[...] 5000-Zeichen-Limit erreicht') if len(detailtext) > 5000 else detailtext
        # response = rocket.chat_send_message(
        #     message={"rid": config.rc_channel,
        #     "tmid": rc_id,
        #     "emoji": ":mag_right:",
        #     "blocks": [{"type": "section",
        #         "text": {"type": "mrkdwn",
        #             "text": croppedtext
        #             }
        #             }]
        #     }
        # )
        response = rocket.chat_post_message(
            room_id=config.rc_channel,
            tmid=rc_id,
            text=croppedtext
        )

        logger.info(f"📊 Detail-Thread: API Response Status: {response.status_code}")

        if response.status_code in [200, 201]:
            logger.info(f"🎯 Rocket-Chat Detail Thread erfolgreich erstellt!")
            return response.json()['message']['_id'] # returns the message ID
        else:
            logger.error(f"❌ Fehler beim Erstellen des RocketChat Detail Threads: {response.status_code}")
            logger.error(f"📄 Response Text: {pformat(response.text)}")
            return None

    except Exception as e:
        logger.error(f"❌ Unerwarteter Fehler beim Erstellen des RocketChat Detail Threads: {e}")
        logger.error(traceback.format_exc())
        return None

def rc_post_template(rocket: RocketChat, 
                    config: Config,
                    email_data: Dict[str, str], 
                    rc_id: str) -> Optional[str]:
    try:
        logger.info(f"🚀 Poste Protokoll Template in Thread unter Nachricht mit ID {rc_id} ({email_data['sender_name']})")
        text=f"Protokoll-Vorlage: Sende sie nach der Beratung ausgefüllt in diesen Thread.\n```\n@fb01bot : Protokoll zu {email_data['sender_name']} (tm_id={rc_id})\n\n--- **Beratung?** (Präsenz/Zoom/Keine)---\nPräsenz\n--- **Datum d. Beratung** (TT.MM.JJJJ) ---\n\n--- **Dauer d. Beratung** in Minuten ---\n45\n--- **Tandempartner∗in** (@uk...) ---\n@\n--- **Vorbereitungszeit aller Beratenden addiert**, in Minuten, ohne Email-Verkehr ---\n0\n--- **Nachbereitungszeit aller Beratenden addiert**, in Minuten, ohne Email-Verkehr ---\n10\n--- **Nummer der Beratung** (für dieses Anliegen) (1, 2, 3...) ---\n1\n--- **Schwierigkeitsgrad der Gesprächssituation** (0 = super easy - 10 = sehr herausfordernd) ---\n\n--- **Herausforderungen** (Schlagworte) ---\n\n--- **Inhaltliche Themen / Analysemethoden** (Schlagworte) ---\n\n--- **Das Anliegen konnte zufriedenstellend geklärt werden** (0 = gar nicht - 10 = äußerst gut) ---\n\n--- **Anliegen und gegebene Ratschläge** (Freitext) ---\n\n```"
        response = rocket.chat_post_message(
            room_id=config.rc_channel,
            tmid=rc_id,
            text=text
        )

        logger.info(f"📊 Protokoll Template Message: API Response Status: {response.status_code}")

        if response.status_code in [200, 201]:
            logger.info(f"🎯 Rocket-Chat Protokoll Template erfolgreich versandt!")
            return response.json()['message']['_id'] # returns the message ID
        else:
            logger.error(f"❌ Fehler beim Versenden des RocketChat Protokoll Templates: {response.status_code}")
            logger.error(f"📄 Response Text: {pformat(response.text)}")
            return None

    except Exception as e:
        logger.error(f"❌ Unerwarteter Fehler beim Versenden des RocketChat Protokoll Templates: {e}")
        logger.error(traceback.format_exc())
        return None


def process_all_inbox(config: Config,
                        account: Account,
                        processed_emails: Set[str],
                        rocket: RocketChat):
    pass

def process_email(config: Config, account: Account, message: Message, processed_emails: Set[str], rocket: RocketChat, stats: StatsTableManager) -> bool:
    """Verarbeitet eine einzelne E-Mail."""
    try:
        message_id = message.message_id
        subject = message.subject or "Kein Subject"
        logger.info(f"\n=== Verarbeite E-Mail ===")
        logger.info(f"Message ID: {message_id}")
        logger.info(f"Subject: {subject}")
    except Exception as e:
        logger.error(f"Fehler beim Extrahieren der Message ID oder Subject Fields: {e}")

    if message_id in processed_emails:
        logger.info(f"⏭️ Überspringe - bereits zu RocketChat gesendet")
        return False

    logger.info(f"Führe TYPO3-Prüfung durch...")

    if not is_typo3_contact_form(message):
        logger.info(f"Nicht als TYPO3-Kontaktformular erkannt")
        return False

    logger.info(f"🎯 TYPO3-Kontaktformular gefunden: {subject}")

    email_data = parse_email_data(message)
    # try except weil RocketChat Session Tokens ablaufen können nach default 90 Tagen
    # unbekannt wie lange in unserer Installation gültig.
    try:
        rc_id = rc_post_message(config, email_data, rocket = rocket)
    except RocketAuthenticationException as e:
        logger.error(f"Fehler bei RocketChat API Authentifizierung - möglicherweise ist Session Token abgelaufen.{e}")
        rocket_chat_login(config)
        logger.info("Login wurde erneuert. Versuche RocketChat Message noch mal zu posten:")
        rc_id = rc_post_message(config, email_data, rocket = rocket)
    rc_post_detail_thread(config = config, rocket = rocket, email_data = email_data, rc_id = rc_id)
    save_processed_email(filename=config.processed_file, message_id=message_id)
    # collect keys and data to be saved in stats.csv
    try:
        allowed_keys = set(stats.HEADERS)
        mail_record = {k: v for k, v in email_data.items() if k in allowed_keys}
        mail_record.update({'tmid': rc_id}) # add the thread message id
    except:
        logger.error("Fehler beim Sammeln der Email-Daten für die Statistik")
    stats.append_record(mail_record) # save data to stats.csv
    rc_post_template(config = config, 
        rocket = rocket, 
        email_data = email_data, 
        rc_id = rc_id)
    return True

def process_many_emails(messages: list, config: Config, account: Account, processed_emails: Set[str],
                    rocket: RocketChat, stats: StatsTableManager):
    """Verarbeitet viele E-Mails."""
    try:
        logger.info(f"Verarbeite {len(messages)} E-Mails...")
        for message in messages:
            try:
                process_email(config, account, message, processed_emails, rocket, stats)
            except Exception as e:
                logger.error(f"Fehler beim Verarbeiten der E-Mail {message.message_id}: {e}")
                import traceback
                logger.error(traceback.format_exc())
        logger.info(f"Verarbeitung der Mails abgeschlossen.")
    except Exception as e:
        logger.error(f"Fehler beim Verarbeiten der E-Mails: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise

def sync_emails(account: Account):
    """
    Benötigt ein Account-Objekt von exchangelib.
    Synchronisiert nur neue Emails. Beim ersten Sync wird die gesamte INBOX
    abgerufen, der Status wird in inbox.item_sync_state gespeichert.
    """
    logger.info("Synchronisiere: Hole neue Emails...")
    inbox = account.inbox
    messages = []
    only_fields = ['headers', 'subject', 'sender', 'datetime_received', 'datetime_sent', 'body']
    try:
        for change_type, item in inbox.sync_items(only_fields=only_fields):
            if change_type == "create":
                messages.append(item)
        logger.info(f"INBOX enthält {len(messages)} neue Email(s) seit dem letzten Sync.")
        return messages
    except Exception as e:
        logger.error(f"Fehler beim Synchronisieren der Emails: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise

def maintain_notification_streaming(account: Account,
                                    config: Config,
                                    processed_emails: Set[str],
                                    stats: StatsTableManager,
                                    rocket: RocketChat,
                                    timeout_minutes: int=29,
                                    only_fields = ['headers', 'subject', 'sender', 'datetime_received', 'datetime_sent', 'body', 'message_id']):
    """:params: inbox = Account.inbox
    :params: timeout_minutes = Positive integer between 1 and 29 (internally, 1 minute is added)
    """
    inbox = account.inbox
    while True:  
        try:
            logger.info("🛜 Starte Notification Streaming Subscription.")  
            with inbox.streaming_subscription() as subscription_id: 
                logger.info("📭 Warte auf neue Mails.")
                for notification in inbox.get_streaming_events(subscription_id, connection_timeout=timeout_minutes):  
                    for event in notification.events:  
                        if isinstance(event, NewMailEvent):  
                            # Get the specific new mail item by ID
                            logger.info("📬 Neue Mail!") 
                            # time.sleep(1) # wait for the server to completely put the mail in INBOX
                            # Fetch only this specific item with only the fields we need  
                            items = list(account.fetch([event.item_id], only_fields=only_fields))
                            item = items[0]
                            #logger.info(f"Inhalt von items:\n{pformat(items)}")
                            logger.info("Starte Verarbeitung der neuen Mail") 
                            process_email(config=config, 
                                            account=account, 
                                            message=item,
                                            processed_emails=processed_emails,
                                            rocket=rocket,
                                            stats=stats)
                            logger.info("📭 Warte auf weitere neue Mails.")
        except (ConnectionError, TimeoutError) as e:  
            logger.error(f"Verbindungsfehler oder Timeout während des Empfangens der Notifications: Verbindung wird in 5s wieder hergestellt: {e}")  
            time.sleep(5)  # Brief pause before reconnecting  
            continue

# Protokoll-Empfangslogik
def parse_protocol_message(msg_text):
    """
    Wird angewendet auf den 'msg'-Inhalt einer Mention aus dem chat.getMentions JSON Output
    Parses a protocol message with alternating '--- variable ---' and 'value' blocks.

    Returns a dictionary with cleaned variable names as keys and their corresponding values.
    """
    protocol_data = {}

    # Parse the header for meta-info (e.g., tm_id)
    # header_match = re.search(r'tm_id=([a-zA-Z0-9]+)', msg_text)
    # if header_match:
    #     protocol_data['tmid'] = header_match.group(1)
    
    # Split the message into blocks
    blocks = re.split(r'---', msg_text)
    blocks = [b.strip() for b in blocks]  # keep '' elements if any
    blocks = blocks[1:]  # discard first block   
    # Pair variable names with values
    i = 0
    while i < len(blocks) - 1:
        var_line = blocks[i]
        val_line = blocks[i+1]
        
        # Clean variable name (remove markdown formatting, parenthesis)
        # var_name = re.sub(r'\*\*|\(.*?\)', '', var_line).strip()
        # var_name = re.sub(r'\s+', ' ', var_name)  # Collapse whitespace
        var_name = f'col_{i}'

        protocol_data[var_name] = val_line.strip()
        i += 2
    
    new_names = ['beratung_type', 'beratung_datum', 'beratung_dauer',
        'tandem', 'vorbereitung', 'nachbereitung', 'beratung_nr', 'schwierigkeit',
        'herausforderungen', 'inhalt', 'klärung', 'ratschläge'] 

    output = {new_names[i]: v for i, (k, v) in enumerate(protocol_data.items())}
    for name in new_names:
        output.setdefault(name, '') # use empty strings instead of NaN.
    return output

def get_room_id(config: Config, rocket: RocketChat):
    cache_file = "room_id_cache.txt"
    room_id = None

    # Try to read cache
    if os.path.exists(cache_file):
        logger.info("Room-ID Cache Datei gefunden.")
        with open(cache_file, "r") as f:
            contents = f.read().split("=")
            if len(contents) == 2 and contents[0] == config.rc_channel:
                room_id = contents[1]

    # If not cached or cache invalid, fetch and update cache
    if room_id is None:
        try:
            logger.info("📡 Frage Room-ID von RocketChat API ab")
            roomid_response = rocket.rooms_info(room_name=re.sub('#', '', config.rc_channel))
            room_id = json.loads(roomid_response.text)['room']['_id']
        except Exception as e:
            logger.error("Fehler beim Abrufen der Room-ID für den RocketChat-Kanal: %s", e)
            room_id = None
        if room_id is not None:
            with open(cache_file, "w") as f:
                f.write(f"{config.rc_channel}={room_id}")

    return room_id


def rocketchat_get_protocols(config: Config, rocket: RocketChat):
    try:
        logger.info("📡 Rufe Mentions von Rocketchat API ab.")
        room_id = get_room_id(config, rocket)
        response = rocket.chat_get_mentioned_messages(room_id)
        logger.info(f"Status: {response.status_code}")
    except:
        logger.error("Fehler beim Abrufen der Mentions.")
    try: 
        mentions = json.loads(response.text)
        # Extract desired fields
        mentionlist = []
        for mention in mentions.get("messages", []):
            temp = {
                'msg_text': mention.get("msg"),
                'protocol_send_date': mention.get("ts"),
                'protocol_sender_name': mention.get("u", {}).get("name"),
                'protocol_sender_user': mention.get("u", {}).get("username"),
                'tmid': mention.get("tmid"),
                'protocol_msg_id': mention.get("_id")
            }
            mentionlist.append(temp)
        logger.info(f"{len(mentionlist)} Mentions gefunden.")
        mentiondf = pd.DataFrame(mentionlist)
        # Filtere nur die Protokolle und schmeiß den Rest heraus
        mentiondf = mentiondf[mentiondf['msg_text'].str.startswith('@fb01bot : Protokoll zu ')]
        # Nachrichten vom Bot an sich selbst rausschmeißen
        mentiondf = mentiondf[mentiondf['protocol_sender_user'] != 'fb01bot']
        logger.info(f"Davon sind {len(mentiondf)} Protokolle")
        logger.info(glimpse(mentiondf))
        return mentiondf
    except Exception as e:
        logger.error(f"Fehler beim Verarbeiten der Mentions: {e}")
        return None

def process_protocols(mentiondf: pd.DataFrame, stats: StatsTableManager):
    try:
        logger.info("Verarbeite die erhaltenen Protokolle")
        # parse protocol data. 
        dicts_series = mentiondf['msg_text'].apply(parse_protocol_message)
        parsed_protocols = pd.DataFrame(dicts_series.tolist())
        logger.info(f"ParsedProtocols: {glimpse(parsed_protocols)}")
        mentiondf = mentiondf.reset_index(drop=True)
        parsed_protocols = parsed_protocols.reset_index(drop=True)
        try:
            assert mentiondf.index.equals(parsed_protocols.index), "Indizes stimmen nicht überein"
            assert mentiondf.shape[0] == parsed_protocols.shape[0], "Protokoll-Metadaten-Tabelle und Protokoll-Inhaltstabelle haben unterschiedliche Anzahl von Zeilen. Das sollte nicht so sein"
            merged_df = pd.concat([mentiondf, parsed_protocols], axis=1)
            logger.info(f"merged_df: {len(merged_df)}")
        except AssertionError as e:
            logger.error(f"Fehler: Merging der geparsten Protokolle in den Datensatz mit Protokoll-Metadaten nicht möglich: {e}")
        # save merged df
        stats.save_df2(merged_df.drop(columns=['msg_text']))
    except Exception as e:
        logger.error(f"Fehler in process_protocols: {e}")

def main():
    """Hauptfunktion."""
    config = Config()
    stats = StatsTableManager(logger=logger)
    try:
        account = init_exchange_connection(config)
        rocket = rocket_chat_login(config)
        processed_emails=load_processed_emails(config.processed_file)
        logger.info("Lade max. 100 Emails aus der INBOX")
        messages = list(account.inbox.all().order_by('-datetime_received')[:100])
        logger.info(f"{len(messages)} Emails geladen.")
        clean_up_processed_file(config.processed_file, messages, processed_emails)
        process_many_emails(messages, config, account, processed_emails, rocket, stats)
        mentiondf = rocketchat_get_protocols(config = config, rocket = rocket)
        process_protocols(mentiondf, stats)
    except Exception as e:
        logger.error(f"Fehler beim ersten Abruf: {e}")
    try:
        maintain_notification_streaming(account, config, processed_emails, stats, rocket, 29)
        pass    
    except Exception as e:
        logger.error(f"Fehler beim Notification Streaming und Verarbeiten neuer Mails: {e}")
        logger.error(traceback.format_exc())
if __name__ == "__main__":
    main()