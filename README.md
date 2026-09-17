# Fase 1 — Banco + Auth + Base + FinancialPeriod mínimo

Ver o relatório técnico completo entregue na conversa (RELATORIO-FASE1.md) para
todos os detalhes de arquitetura, constraints, testes e decisões.

## Rodando localmente

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env  # edite DATABASE_URL e JWT_SECRET_KEY
./venv/bin/alembic upgrade head
./venv/bin/uvicorn app.main:app --reload
```

Interface mínima de validação: http://localhost:8000/app/
Documentação interativa (Swagger, gerada automaticamente pelo FastAPI): http://localhost:8000/docs

## Rodando os testes

Requer um banco `hamburgueria_fase1_test` separado do de desenvolvimento (os testes
fazem TRUNCATE entre cada teste).

```bash
./venv/bin/pytest tests/ -v
```
