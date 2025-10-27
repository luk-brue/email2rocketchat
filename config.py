from dotenv import load_dotenv

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