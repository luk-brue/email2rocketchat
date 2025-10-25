import os
import pandas as pd

class StatsTableManager:
    """
    Manages a stats table stored in a CSV file.
    
    - On init, checks for the file and creates it if missing.
    - Provides methods to append new records and update rows.
    
    Parameters:
    - logger: a logging object with .info and .error methods.
    """
    FILENAME = 'stats.csv'
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
        'beratung_nr',
        'protocol_send_date'
    ]

    def __init__(self, logger):
        self.logger = logger
        if not os.path.exists(self.FILENAME):
            self.logger.info(f"StatsTableManager: {self.FILENAME} not found. Creating new file.")
            pd.DataFrame(columns=self.HEADERS).to_csv(self.FILENAME, index=False)
        self._load_df()

    def _load_df(self):
        self.df = pd.read_csv(self.FILENAME, dtype=str)
        self.df.fillna('', inplace=True)  # treat empty as ""

    def _save_df(self):
        self.df.to_csv(self.FILENAME, index=False)
        self.logger.info("StatsTableManager: Wrote stats to csv.")

    def append_record(self, record_dict):
        """Add a new row. Missing fields default to empty string."""
        new_row = {h: record_dict.get(h, "") for h in self.HEADERS}
        self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)
        self.logger.info(f"StatsTableManager: Daten hinzugefügt von {new_row['sender_name']}.")
        self._save_df()

    def update_or_append_record(self, id_dict, update_dict):
        """
        Update an existing row or append a new one.
        - id_dict: should have 'tmid', optionally 'beratung_nr', 'protocol_send_date'
        - update_dict: fields to fill in (e.g. 'beratung_nr', 'protocol_send_date')
        """
        tmid = id_dict.get('tmid', '')
        beratung_nr = id_dict.get('beratung_nr', '')
        protocol_send_date = id_dict.get('protocol_send_date', '')

        # Filter by tmid first
        matches = self.df[self.df['tmid'] == tmid]
        if beratung_nr:
            matches = matches[matches['beratung_nr'] == beratung_nr]
        elif protocol_send_date:
            matches = matches[matches['protocol_send_date'] == protocol_send_date]

        if not matches.empty:
            # Check for beratung_nr match
            for idx, row in matches.iterrows():
                # Wenn neues Protokoll hinterlegt wird wegen neuer Beratung
                if beratung_nr and row['beratung_nr'] != beratung_nr:
                    # Create new row
                    new_row = {**row, **update_dict}
                    self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)
                    self.logger.info(f"StatsTableManager: beratung_nr not existing yet, created new row: {new_row}")
                else:
                    # Update in place
                    for k, v in update_dict.items():
                        if row[k] != v:
                            self.logger.info(f"StatsTableManager: Updating {k} from {row[k]} to {v} for row index {idx}")
                            self.df.at[idx, k] = v
            self._save_df()
        else:
            # No match, create new row
            new_row = {h: id_dict.get(h, "") for h in self.HEADERS}
            for k, v in update_dict.items():
                new_row[k] = v
            self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)
            self.logger.info(f"StatsTableManager: No matching row, appended new row: {new_row}")
            self._save_df()