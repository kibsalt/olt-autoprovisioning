import sys
sys.path.insert(0, ".")
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv
load_dotenv(".env")
url = os.getenv("OLT_DATABASE_URL", "").replace("+aiomysql", "")
eng = create_engine(url)
c = eng.connect()
try:
    c.execute(text("ALTER TABLE olts ADD COLUMN enable_password VARCHAR(512) NULL"))
    c.commit()
    print("Column enable_password added OK")
except Exception as e:
    print("Skip:", str(e)[:100])
