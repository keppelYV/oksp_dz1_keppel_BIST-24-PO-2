import os
import re
from dotenv import load_dotenv

load_dotenv()
DB_SCHEMA = os.getenv('DB_SCHEMA', 'imya_keppel')
if not re.fullmatch(r'[a-z][a-z0-9_]*', DB_SCHEMA):
    raise RuntimeError('DB_SCHEMA must contain only lowercase Latin letters, digits and underscores')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql+psycopg://app:changeme@localhost:5432/imya_keppel_db')
DEMO_USERNAME = os.getenv('DEMO_USERNAME', 'demo')
DEMO_PASSWORD = os.getenv('DEMO_PASSWORD', 'demo123')
