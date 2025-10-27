import pandas as pd
import re
import os
from rocketchat_API.rocketchat import RocketChat
import json
from config import Config

class RocketChatMessageListener:
    """
    - There is no easily accessible notification streaming except when registering your application
    - We do not have admin rights therefore notifications are not possible. 
    - Therefore, periodically fetch messages that are relevant to the bot. 
    - Mentions are what is relevant. The mentions are scanned for special strings which
      are defined in this class. 
    - The special strings should be a flexible input to provide extensibility
    - The functions will return actionable items
    - This class manages a database with already processed m
    - Act on the message commands
    - depends on the RocketChat API Package
    """

RID_CACHE_FILE = "room_id_cache.txt"
RECEIVED_MENTIONS_FILE = "received_mentions.csv"
HEADERS = ['msg_text', 'msg_ts', 'msg_sender_name', 'msg_sender_user', 'tmid', 'msg_id']
CMD_STRINGS = ['@fb01bot : Protokoll zu ']

def __init__(self, rocket: RocketChat, config: Config, logger):
    self.channelname = config.rc_channel
    self.rocket = rocket
    self.logger = logger
    self._get_room_id()
    self._get_received_mentions_cache()

def _read_received_mentions_cache(self):
    if not os.path.exists(self.RECEIVED_MENTIONS_FILE):
        self.logger.info(f"RocketChatMessageListener: {self.RECEIVED_MENTIONS_FILE} nicht gefunden. Erstelle neue Datei.")
        pd.DataFrame(columns=self.HEADERS).to_csv(self.RECEIVED_MENTIONS_FILE, index=False)
    self.received_mentions = pd.read_csv(self.RECEIVED_MENTIONS_FILE, dtype=str)
    self.logger.info(f"RocketChatMessageListener: {self.RECEIVED_MENTIONS_FILE} eingelesen.")

def _write_received_mentions_cache(self):
        self.received_mentions.to_csv(self.RECEIVED_MENTIONS_FILE, index=False)
        self.logger.info("RocketChatMessageListener: Daten in CSV auf Festplatte gespeichert.")

def _get_room_id(self):
    
    self.room_id = None
    # Try to read cache
    if os.path.exists(self.RID_CACHE_FILE):
        self.logger.info("Room-ID Cache Datei gefunden.")
        with open(self.RID_CACHE_FILE, "r") as f:
            contents = f.read().split("=")
            if len(contents) == 2 and contents[0] == self.channelname:
                self.room_id = contents[1]

    # If not cached or cache invalid, fetch and update cache
    if self.room_id is None:
        try:
            self.logger.info("📡 Frage Room-ID von RocketChat API ab")
            roomid_response = rocket.rooms_info(room_name=re.sub('#', '', self.channelname))
            self.room_id = json.loads(roomid_response.text)['room']['_id']
        except Exception as e:
            self.logger.error("Fehler beim Abrufen der Room-ID für den RocketChat-Kanal", e)
            self.room_id = None
        if self.room_id is not None:
            with open(self.RID_CACHE_FILE, "w") as f:
                f.write(f"{self.rc_channel}={self.room_id}")

    return self.room_id

def rocketchat_get_protocols(self): # need work
    
    try: 
        mentions = json.loads(response.text)
        # Extract desired fields
        mentionlist = []
        for mention in mentions.get("messages", []):
            temp = {
                'msg_text': mention.get("msg"),
                'msg_ts': mention.get("ts"),
                'msg_sender_name': mention.get("u", {}).get("name"),
                'msg_sender_user': mention.get("u", {}).get("username"),
                'tmid': mention.get("tmid"),
                'msg_id': mention.get("_id")
            }
            mentionlist.append(temp)
        self.logger.info(f"{len(mentionlist)} Mentions gefunden.")
        mentiondf = pd.DataFrame(mentionlist)
        # Filtere nur die Protokolle und schmeiß den Rest heraus
        mentiondf = mentiondf[mentiondf['msg_text'].str.startswith(self.CMD_STRINGS)]
        # Nachrichten vom Bot an sich selbst rausschmeißen
        mentiondf = mentiondf[mentiondf['protocol_sender_user'] != 'fb01bot']
        self.logger.info(f"Davon sind {len(mentiondf)} Protokolle")
        self.logger.info(glimpse(mentiondf))
        return mentiondf
    except Exception as e:
        self.logger.error(f"Fehler beim Verarbeiten der Mentions: {e}")
        return None

def fetch_new_mentions(self, mentioncount = 100):
    """
    gets 100 Mentions in the configured channel
    """
    try:
        self.logger.info("📡 Rufe Mentions von Rocketchat API ab.")
        response = self.rocket.chat_get_mentioned_messages(self.room_id, count = mentioncount)
        self.logger.info(f"Status: {response.status_code}")
        return response
    except Exception as e:
        self.logger.error(f"Fehler beim Abrufen der Mentions: {e}")