from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import auth, business, expense, financial_period, fixed_cost, ingredient, pricing, product, promotion, purchase, recipe, reports, sale, sales_channel, supplier

app = FastAPI(
    title="Plataforma de Gestão para Negócios de Alimentação — Fase 1",
    description="Banco + Auth + Base + FinancialPeriod mínimo. Fonte técnica: contrato-tecnico-implementacao.md",
    version="1.0.0-fase1",
)

app.include_router(auth.router)
app.include_router(business.router)
app.include_router(financial_period.router)
app.include_router(ingredient.router)
app.include_router(supplier.router)
app.include_router(purchase.router)
app.include_router(recipe.router)
app.include_router(product.router)
app.include_router(sales_channel.router)
app.include_router(pricing.router)
app.include_router(sale.router)
app.include_router(promotion.router)
app.include_router(fixed_cost.router)
app.include_router(expense.router)
app.include_router(reports.router)

app.mount("/app", StaticFiles(directory="static", html=True), name="static")


@app.get("/health")
def health():
    return {"status": "ok", "fase": 1}
