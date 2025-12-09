from app.core.authdb import SessionLocal

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()