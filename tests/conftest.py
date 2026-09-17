import os
import uuid

# Aponta para o banco de TESTE antes de qualquer import da aplicação —
# nunca rodamos testes contra o banco de desenvolvimento.
os.environ["DATABASE_URL"] = (
    "postgresql+psycopg2://hamburgueria:dev_local_only_pw@localhost:5432/hamburgueria_fase1_test"
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.main import app

TABLES_IN_FK_ORDER = [
    "expenses",
    "fixed_costs",
    "promotions",
    "pizza_sabores",
    "combo_items",
    "partial_returns",
    "sale_items",
    "sales",
    "product_channel_pricings",
    "sales_channels",
    "products",
    "recipe_items",
    "recipes",
    "inventory_movements",
    "purchase_items",
    "purchases",
    "suppliers",
    "ingredient_price_snapshots",
    "ingredients",
    "idempotency_records",
    "financial_periods",
    "revoked_tokens",
    "users",
    "operation_configs",
    "businesses",
]


@pytest.fixture(autouse=True)
def clean_database():
    """Limpa todas as tabelas antes de CADA teste — usamos TRUNCATE (não transação
    envolvente) exatamente porque os testes de concorrência precisam de conexões
    de banco genuinamente independentes entre threads."""
    with engine.begin() as conn:
        for table in TABLES_IN_FK_ORDER:
            conn.execute(text(f'TRUNCATE TABLE "{table}" CASCADE'))
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def signup_and_get_token(client: TestClient, *, email: str | None = None, business_name: str = "Hamburgueria Teste"):
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post(
        "/auth/signup",
        json={
            "business_name": business_name,
            "segment": "hamburgueria",
            "timezone": "America/Sao_Paulo",
            "email": email,
            "password": "senha-forte-123",
        },
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    return token, email
