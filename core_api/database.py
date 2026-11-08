import os
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = os.path.join(os.path.dirname(__file__), "api_queue.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskTracker(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, index=True)
    # UPLOADED, STT_PROCESSING, STT_DONE, EMR_PROCESSING, RETRYING_EMR_IN_xS, COMPLETED, ERROR
    status = Column(String, default="UPLOADED")
    audio_path = Column(String, nullable=True)
    stt_text = Column(String, nullable=True)        # dictionary-corrected transcript
    emr_json = Column(String, nullable=True)
    error_message = Column(String, nullable=True)
    retry_count = Column(Integer, default=0)
    # added 2026-11 (auto-migrated below)
    raw_stt_text = Column(String, nullable=True)    # transcript exactly as the ASR produced it
    stt_meta = Column(String, nullable=True)        # JSON: engine, segments, dictionary changes, timings
    consent_id = Column(String, nullable=True)
    source = Column(String, nullable=True)          # pharmacist | backoffice | test
    audio_filename = Column(String, nullable=True)
    created_at = Column(String, nullable=True)
    updated_at = Column(String, nullable=True)
    confirmed_emr_json = Column(String, nullable=True)  # pharmacist-reviewed EMR
    confirmed_at = Column(String, nullable=True)


Base.metadata.create_all(bind=engine)

# Lightweight migration: add new columns to an existing tasks table.
with engine.begin() as _conn:
    _have = {c["name"] for c in inspect(_conn).get_columns("tasks")}
    for _col in ("raw_stt_text", "stt_meta", "consent_id", "source", "audio_filename",
                 "created_at", "updated_at", "confirmed_emr_json", "confirmed_at"):
        if _col not in _have:
            _conn.execute(text(f"ALTER TABLE tasks ADD COLUMN {_col} VARCHAR"))
