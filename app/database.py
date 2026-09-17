"""
Engine e sessão do SQLAlchemy.

Nenhuma lógica de negócio vive aqui — só a infraestrutura de conexão.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """Dependency do FastAPI: uma sessão por requisição.

    Rollback explícito em qualquer exceção — nunca depende do comportamento implícito
    do pool de conexões para desfazer estado parcial (Comando 10, Parte 20:
    'nenhuma das partes deve permanecer parcialmente persistida')."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
