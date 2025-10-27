import os
import pandas as pd

def glimpse(df):
    print(f"Rows: {df.shape[0]}")
    print(f"Columns: {df.shape[1]}")
    for col in df.columns:
        print(f"$ {col} {df[col].head().values[:20]}")

class StatsTableManager:
    """
    Manages 2 stats tables stored in CSV files.
    
    - On init, checks for the files and creates them if missing.
    - Provides methods to append new records and update rows.
    
    Parameters:
    - logger: a logging object with .info and .error methods.
    """
    FILENAME1 = 'stats.csv'
    FILENAME2 = 'parsed_protocols.csv'
    HEADERS = [
        'sender_name',
        'message_id', # email identifier
        'tmid',
        'received_date',
        'fachsemester',
        'art',
        'betreuung',
        'studiengang',
        'fachgebiet',
    ]

    HEADERS2 = [
        'protocol_send_date',
        'beratung_type', 'beratung_datum', 'beratung_dauer',
        'tandem', 'vorbereitung', 'nachbereitung', 'beratung_nr', 'schwierigkeit',
        'herausforderungen', 'inhalt', 'klärung', 'ratschläge',
        'protocol_sender_name', 'protocol_sender_user', 'protocol_msg_id'
    ]

    def __init__(self, logger):
        self.logger = logger
        if not os.path.exists(self.FILENAME1):
            self.logger.info(f"StatsTableManager: {self.FILENAME1} nicht gefunden. Erstelle neue Datei.")
            pd.DataFrame(columns=self.HEADERS).to_csv(self.FILENAME1, index=False)
        if not os.path.exists(self.FILENAME2):
            self.logger.info(f"StatsTableManager: {self.FILENAME2} nicht gefunden. Erstelle neue Datei.")
            pd.DataFrame(columns=self.HEADERS2).to_csv(self.FILENAME2, index=False)
        self._load_df()
        self._load_df2()

    def _load_df(self):
        self.logger.info(f"StatsTableManager: {self.FILENAME1} gefunden.")
        self.df = pd.read_csv(self.FILENAME1, dtype=str)
        self.logger.info(f"StatsTableManager: {self.FILENAME1} eingelesen.")
        self.df.fillna('', inplace=True)  # treat empty as ""
    def _load_df2(self):
        self.logger.info(f"StatsTableManager: {self.FILENAME2} gefunden.")
        self.df2 = pd.read_csv(self.FILENAME2, dtype=str)
        self.logger.info(f"StatsTableManager: {self.FILENAME2} eingelesen.")
        self.df2.fillna('', inplace=True)

    def _save_df(self):
        self.df.to_csv(self.FILENAME1, index=False)
        self.logger.info("StatsTableManager: Daten in CSV auf Festplatte gespeichert.")
    def _save_df2(self):
        self.df2.to_csv(self.FILENAME2, index=False)
        self.logger.info("StatsTableManager: Daten in CSV auf Festplatte gespeichert.")
    def _append_df2(self):
        self.df2.to_csv(self.FILENAME2, index=False, mode='a', header=False)
        self.logger.info("StatsTableManager: Daten an CSV angehängt.")

    def append_record(self, record_dict):
        """Add a new row. Missing fields default to empty string."""
        new_row = {h: record_dict.get(h, "") for h in self.HEADERS}
        self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)
        self.logger.info(f"StatsTableManager: Daten hinzugefügt von {new_row['sender_name']}.")
        self._save_df()
    
    def save_df2(self, df):
        self.df2 = df
        self._append_df2()