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
    HEADERS = ['msg_text', 'msg_ts', 'msg_sender_name', 'msg_sender_user', 'tmid', 'msg_id', 'rid']
    CMD_STRINGS = ('@fb01bot : Protokoll zu ', '@fb01bot : !send_stats!')

    def __init__(self, rocket: RocketChat, config: Config, logger):
        self.channelname = config.rc_channel
        self.command_channelname = config.rc_command_channel
        self.rocket = rocket
        self.logger = logger
        self._get_room_ids()
        self._read_received_mentions_cache()
        # get protocol mentions from protocol channel
        self.logger.info(f"Hole Command-Mentions für Kanal {self.channelname} -------")
        self._get_cmd_mentions(room_id=self.room_id, starts_with=self.CMD_STRINGS)
        # get command mentions from command channel
        self.logger.info(f"Hole Command-Mentions für Kanal {self.command_channelname} -------")
        self._get_cmd_mentions(room_id=self.command_room_id, starts_with=self.CMD_STRINGS)

    def _read_received_mentions_cache(self):
        if not os.path.exists(self.RECEIVED_MENTIONS_FILE):
            self.logger.info(f"{self.RECEIVED_MENTIONS_FILE} nicht gefunden. Erstelle neue Datei.")
            pd.DataFrame(columns=self.HEADERS).to_csv(self.RECEIVED_MENTIONS_FILE, index=False)
        self.received_mentions = pd.read_csv(self.RECEIVED_MENTIONS_FILE, dtype=str)
        self.logger.info(f"{self.RECEIVED_MENTIONS_FILE} eingelesen.")

    def _write_received_mentions_cache(self):
            self.received_mentions.to_csv(self.RECEIVED_MENTIONS_FILE, index=False)
            self.logger.info("Daten in CSV auf Festplatte gespeichert.")

    def _get_cmd_mentions(self, room_id, starts_with, pagesize = 5):
        """
        maximum pagesize at Uni Kassel is 100 it seems
        """
        # paged mention reception
        dup_test = (False, False)
        pagesize = pagesize
        offset = 0
        new_mentions = pd.DataFrame()
        old_msg_id = set(self.received_mentions.msg_id)
        self.logger.info(f"Aktuell gespeicherte Command-Mentions: {len(self.received_mentions)}")
        while not any(dup_test):
            # fetch mentions
            temp = self.fetch_new_mentions(room_id=room_id,
                starts_with=starts_with,
                mentioncount=pagesize, offset=offset)
            if temp is None: 
                self.logger.info("Keine weiteren Mentions mehr vorhanden - alle geholt")
                break
            # check for duplicate rows
            if old_msg_id:
                dup_test = temp['msg_id'].isin(old_msg_id)
                # will end for loop if the first fetch does not bring any new mentions.
                # this makes the strong assumption the api will always serve newest 
                # montions first. 
            new_mentions = pd.concat([new_mentions, temp])
            self.logger.info(f"Sind unter den eben geholten Mentions (Offset={offset}) bereits lokal gespeicherte? {any(dup_test)}")
            # increment offset
            offset += pagesize
            # if any(dup_test): 
            #     break
        self.logger.info(f"Abruf beendet. Insgesamt {len(new_mentions)} Command-Mentions von der API abgeholt.")
        new_msg_id = set(new_mentions.msg_id)
        self.logger.info(f"Davon waren {len(set.intersection(*[new_msg_id, old_msg_id]))} bereits lokal gespeichert.")
        self.received_mentions = pd.concat([self.received_mentions, new_mentions])
        self.received_mentions.drop_duplicates(inplace=True)
        self._write_received_mentions_cache()

    def _get_room_ids(self):
        
        self.room_id = None
        self.command_room_id = None
        # Try to read cache
        if os.path.exists(self.RID_CACHE_FILE):
            self.logger.info("Room-ID Cache Datei gefunden.")
            with open(self.RID_CACHE_FILE, "r") as f:
                contents = f.read().split("=")
                if len(contents) == 4 and contents[0] == self.channelname:
                    self.room_id = contents[1]
                if len(contents) == 4 and contents[2] == self.command_channelname:
                    self.command_room_id = contents[3]

        # If not cached or cache invalid, fetch and update cache
        if self.room_id is None or self.command_room_id is None:
            try:
                self.logger.info("📡 Frage Room-ID von RocketChat API ab")
                roomid_response = self.rocket.rooms_info(room_name=re.sub('#', '', self.channelname))
                self.room_id = json.loads(roomid_response.text)['room']['_id']
                self.logger.info("📡 Frage Room-ID von RocketChat API ab")
                roomid_response = self.rocket.rooms_info(room_name=re.sub('#', '', self.command_channelname))
                self.command_room_id = json.loads(roomid_response.text)['room']['_id']
            except Exception as e:
                self.logger.error("Fehler beim Abrufen der Room-ID", e)
                self.room_id = None
            if self.room_id is not None:
                with open(self.RID_CACHE_FILE, "w") as f:
                    f.write(f"{self.channelname}={self.room_id}={self.command_channelname}={self.command_room_id}")

    def fetch_new_mentions(self, room_id, starts_with, mentioncount = 100, offset = 100):
        """
        gets mentions in a specific room
        filters them
        returns a pd.DataFrame
        """
        try:
            self.logger.info("📡 Rufe Mentions von Rocketchat API ab.")
            response = self.rocket.chat_get_mentioned_messages(room_id, count = mentioncount, offset = offset)
            self.logger.info(f"Status: {response.status_code}, ResponseText: {len(response.text)} Zeichen")
        except Exception as e:
            self.logger.error(f"Fehler beim Abrufen der Mentions von API: {e}")
            return None
        try: 
            mentions = json.loads(response.text)
            # Extract desired fields
            if not mentions.get("messages", []): # when all messages are fetched return None
                return None
            mentionlist = []
            for mention in mentions.get("messages", []):
                temp = {
                    'msg_text': mention.get("msg"),
                    'msg_ts': mention.get("ts"),
                    'msg_sender_name': mention.get("u", {}).get("name"),
                    'msg_sender_user': mention.get("u", {}).get("username"),
                    'tmid': mention.get("tmid"),
                    'msg_id': mention.get("_id"),
                    'rid': mention.get("rid")
                }
                mentionlist.append(temp)
            self.logger.info(f"{len(mentionlist)} Mentions von API geholt.")
            mentiondf = pd.DataFrame(mentionlist)
            # Nachrichten vom Bot an sich selbst rausschmeißen
            mentiondf = mentiondf[mentiondf['msg_sender_user'] != 'fb01bot']
            # Filtere nach besonderen Start-Sequenzen und schmeiß den Rest heraus
            mentiondf = mentiondf[mentiondf['msg_text'].str.startswith(starts_with)]
            self.logger.info(f"Davon entsprachen {len(mentiondf)} den Kriterien für Command-Mentions.")
            return mentiondf
        except Exception as e:
            self.logger.error(f"Fehler beim Verarbeiten der Mentions: {e}")
            return None
    
