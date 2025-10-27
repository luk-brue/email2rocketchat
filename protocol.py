import re
import os
import pandas as pd
from stats_table_manager import glimpse
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def parse_msg(msg_text):
    """
    Wird angewendet auf den 'msg'-Inhalt einer Mention aus dem chat.getMentions JSON Output
    Parses a protocol message with alternating 'variable and 'value' blocks.

    Returns a dictionary with cleaned variable names as keys and their corresponding values.
    """
    blocks = re.split(r'▸ \*\*', msg_text)
    blocks = blocks[1:]  # discard first block
    valuelist = []
    for b in blocks:
        v = b.strip()
        x = v.split(':\n') 
        if len(x) == 1:
            x = ''
        if len(x) == 2:
            x = x[1]
        valuelist.append(x)
    print(valuelist)
    new_names = ['beratung_type', 'beratung_datum', 'beratung_dauer',
        'tandem', 'vorbereitung', 'nachbereitung', 'beratung_nr', 'schwierigkeit',
        'herausforderungen', 'inhalt', 'klärung', 'ratschläge'] 
    output = dict(zip(new_names, valuelist))
    for name in new_names:
        output.setdefault(name, '') # use empty strings instead of NaN.
    return output

def process(mentiondf: pd.DataFrame):
    try:
        logger.info("Verarbeite die erhaltenen Protokolle")
        # parse protocol data. 
        dicts_series = mentiondf['msg_text'].apply(parse_msg)
        parsed_protocols = pd.DataFrame(dicts_series.tolist())
        logger.info(f"ParsedProtocols: {glimpse(parsed_protocols)}")
        mentiondf = mentiondf.reset_index(drop=True)
        parsed_protocols = parsed_protocols.reset_index(drop=True)
        try:
            assert mentiondf.index.equals(parsed_protocols.index), "Indizes stimmen nicht überein"
            assert mentiondf.shape[0] == parsed_protocols.shape[0], "Protokoll-Metadaten-Tabelle und Protokoll-Inhaltstabelle haben unterschiedliche Anzahl von Zeilen. Das sollte nicht so sein"
            merged_df = pd.concat([mentiondf, parsed_protocols], axis=1)
            merged_df.drop(columns='msg_text', inplace=True)
            logger.info(f"merged_df: {len(merged_df)}")
            return merged_df
        except AssertionError as e:
            logger.error(f"Fehler: Merging der geparsten Protokolle in den Datensatz mit Protokoll-Metadaten nicht möglich: {e}")
        # save merged df
        #stats.save_df2(merged_df.drop(columns=['msg_text']))
    except Exception as e:
        logger.error(f"Fehler in process_protocols: {e}")
        return None