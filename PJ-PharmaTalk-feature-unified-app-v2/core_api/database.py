import os
from sqlalchemy import create_engine, Column, String, Integer, Float
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = os.path.join(os.path.dirname(__file__), "api_queue.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class TaskTracker(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, index=True)
    status = Column(String, default="UPLOADED") # UPLOADED, STT_PROCESSING, EMR_PROCESSING, COMPLETED, ERROR
    audio_path = Column(String, nullable=True)
    stt_text = Column(String, nullable=True)
    emr_json = Column(String, nullable=True)
    error_message = Column(String, nullable=True)
    retry_count = Column(Integer, default=0)

# Create tables automatically
Base.metadata.create_all(bind=engine)
