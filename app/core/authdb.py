from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# The location of the file. It will be created automatically in your root folder.
SQLALCHEMY_DATABASE_URL = "sqlite:///./app.db"

# Create the engine. 
# check_same_thread=False is required ONLY for SQLite. It lets FastAPI's async threads share the connection safely.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# Create the SessionLocal class.
# Each instance of this class will be a database session.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create the Base class.
# Later, models will look like: class User(Base): ...
Base = declarative_base()
