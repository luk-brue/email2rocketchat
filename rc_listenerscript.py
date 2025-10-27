from config import Config
from email2rc import rocket_chat_login
from stats_table_manager import glimpse
from rocketchat_message_listener import RocketChatMessageListener
import protocol
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    config = Config()
    rocket = rocket_chat_login(config)
    msglis = RocketChatMessageListener(rocket, config, logger)
    protomentions = msglis.received_mentions[msglis.received_mentions['rid'] == msglis.room_id]
    logger.info(protomentions)
    merged_df = protocol.process(protomentions)
    if not merged_df is None:
        logger.info(glimpse(merged_df))

if __name__ == "__main__":
    main()