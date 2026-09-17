"""Schemas Pydantic — contratos de entrada/saída da API. Nenhuma lógica de negócio aqui."""
import uuid
import zoneinfo
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, ConfigDict, computed_field, field_validator

from app.models import BaseComissao, MetodoRateio, ModoProporcionalizacaoFixo, Segmento, TipoDesconto, TipoDespesa, TipoProduto, UnidadeCompra, UnidadeVenda

# Comando 12, seção 3: validação de timezone IANA usando exclusivamente a
# biblioteca padrão (zoneinfo) — nenhuma dependência externa adicionada.
_VALID_IANA_TIMEZONES = zoneinfo.available_timezones()


# ---------------------------------------------------------------------------
# Auth / Signup
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    business_name: str = Field(min_length=1, max_length=200)
    segment: Segmento
    timezone: str = Field(min_length=1, max_length=64, description="IANA timezone, ex: America/Sao_Paulo")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("timezone")
    @classmethod
    def timezone_deve_ser_iana_valido(cls, value: str) -> str:
        if value not in _VALID_IANA_TIMEZONES:
            raise ValueError(
                f"'{value}' não é um identificador de timezone IANA válido "
                f"(ex: America/Sao_Paulo, America/Fortaleza, Europe/Lisbon, UTC)"
            )
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------------------------------------------------------------------------
# Business
# ---------------------------------------------------------------------------

class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    segment: Segmento
    currency: str
    timezone: str
    created_at: datetime


# ---------------------------------------------------------------------------
# OperationConfig
# ---------------------------------------------------------------------------

class OperationConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    volume_mensal_estimado: float | None
    imposto_percentual: float
    custo_hora_funcionario_centavos: int
    metodo_rateio: MetodoRateio
    cmv_alvo_max: float
    margem_alvo_alta: float
    margem_alvo_baixa: float
    margem_perigosa: float
    contrib_alvo_alta: float
    contrib_alvo_baixa: float
    aliquota_imposto_lucro: float | None
    modo_proporcionalizacao_fixo: ModoProporcionalizacaoFixo
    dias_operacao_por_mes: int | None
    alertar_taxa_zero: bool
    base_comissao_padrao: BaseComissao


class OperationConfigUpdate(BaseModel):
    """Todos os campos opcionais — PATCH parcial. metodo_rateio propositalmente ausente:
    é fixo em horas_produtivas (Comando 10, seção 5) e não deve ser editável pela API."""
    volume_mensal_estimado: float | None = None
    imposto_percentual: float | None = Field(default=None, ge=0, lt=100)
    custo_hora_funcionario_centavos: int | None = Field(default=None, ge=0)
    cmv_alvo_max: float | None = Field(default=None, ge=0, le=100)
    margem_alvo_alta: float | None = Field(default=None, ge=0, le=100)
    margem_alvo_baixa: float | None = Field(default=None, ge=0, le=100)
    margem_perigosa: float | None = Field(default=None, ge=0, le=100)
    contrib_alvo_alta: float | None = Field(default=None, ge=0, le=100)
    contrib_alvo_baixa: float | None = Field(default=None, ge=0, le=100)
    aliquota_imposto_lucro: float | None = Field(default=None, ge=0, lt=100)
    modo_proporcionalizacao_fixo: ModoProporcionalizacaoFixo | None = None
    dias_operacao_por_mes: int | None = Field(default=None, ge=1, le=31)
    alertar_taxa_zero: bool | None = None
    base_comissao_padrao: BaseComissao | None = None


# ---------------------------------------------------------------------------
# FinancialPeriod
# ---------------------------------------------------------------------------

class FinancialPeriodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    data_hora_inicio: datetime
    data_hora_fim: datetime | None

    @computed_field
    @property
    def status(self) -> str:
        return "ABERTO" if self.data_hora_fim is None else "FECHADO"


class ClosePeriodRequest(BaseModel):
    idempotency_key: str | None = Field(
        default=None, max_length=200, description="Recomendado: UUID gerado pelo cliente"
    )


# ---------------------------------------------------------------------------
# Ingredient (Fase 2 — cadastro básico)
# ---------------------------------------------------------------------------

class IngredientCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    unidade_compra: UnidadeCompra
    perda_percentual: float = Field(default=0, ge=0, lt=90)
    estoque_minimo: float | None = Field(default=None, ge=0)


class IngredientUpdate(BaseModel):
    """PATCH parcial — todos os campos opcionais, só altera o que for enviado."""
    nome: str | None = Field(default=None, min_length=1, max_length=200)
    unidade_compra: UnidadeCompra | None = None
    perda_percentual: float | None = Field(default=None, ge=0, lt=90)
    estoque_minimo: float | None = Field(default=None, ge=0)


class IngredientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    nome: str
    unidade_compra: UnidadeCompra
    perda_percentual: float
    estoque_minimo: float | None
    ativo: bool
    criado_em: datetime
    estoque_atual: float = Field(description="Sempre calculado na hora a partir dos movimentos — nunca um número fixo salvo")
    unidade_estoque: str = Field(description="A unidade em que estoque_atual está expresso: sempre a unidade-base (g, ml ou un), nunca a unidade de compra (kg/L)")


# ---------------------------------------------------------------------------
# IngredientPriceSnapshot (Fase 2 — histórico de preço)
# ---------------------------------------------------------------------------

class IngredientPriceCreate(BaseModel):
    preco_pago_centavos: int = Field(ge=0, description="Total pago, em centavos (ex: R$120,00 = 12000)")
    quantidade_comprada: float = Field(gt=0, description="Na unidade de compra do insumo (ex: 5 para 5kg)")


class IngredientPriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ingredient_id: uuid.UUID
    preco_pago_centavos: int
    quantidade_comprada: float
    custo_por_base_milicentavos: int
    vigente_desde: datetime
    origem: str


# ---------------------------------------------------------------------------
# Supplier (Fase 2 — Fornecedor)
# ---------------------------------------------------------------------------

class SupplierCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    contato: str | None = Field(default=None, max_length=200)


class SupplierUpdate(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=200)
    contato: str | None = Field(default=None, max_length=200)


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    nome: str
    contato: str | None
    ativo: bool
    criado_em: datetime


# ---------------------------------------------------------------------------
# Purchase (Fase 2 — Compra). Toda compra nasce "recebida" nesta etapa —
# não existe estado "pendente" ainda (simplificação combinada previamente).
# ---------------------------------------------------------------------------

class PurchaseItemCreate(BaseModel):
    ingredient_id: uuid.UUID
    quantidade_comprada: float = Field(gt=0)
    preco_total_centavos: int = Field(ge=0)


class PurchaseCreate(BaseModel):
    supplier_id: uuid.UUID
    itens: list[PurchaseItemCreate] = Field(min_length=1)
    frete_centavos: int = Field(default=0, ge=0)
    outros_custos_centavos: int = Field(default=0, ge=0)
    data: datetime | None = Field(default=None, description="Se omitido, usa o momento do registro")


class PurchaseItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ingredient_id: uuid.UUID
    quantidade_comprada: float
    preco_total_centavos: int
    frete_alocado_centavos: int
    outros_custos_alocado_centavos: int
    price_snapshot_id: uuid.UUID


class PurchaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    supplier_id: uuid.UUID
    data: datetime
    frete_centavos: int
    outros_custos_centavos: int
    criado_em: datetime
    itens: list[PurchaseItemOut] = []


# ---------------------------------------------------------------------------
# Recipe (Fase 2 — Ficha Técnica)
# ---------------------------------------------------------------------------

class RecipeCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    tempo_preparo_minutos: float | None = Field(default=None, ge=0)


class RecipeUpdate(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=200)
    tempo_preparo_minutos: float | None = Field(default=None, ge=0)


class RecipeItemCreate(BaseModel):
    ingredient_id: uuid.UUID
    quantidade: float = Field(gt=0, description="Sempre na unidade-base do insumo: g, ml ou un")


class RecipeItemUpdateQty(BaseModel):
    quantidade: float = Field(gt=0)


class RecipeItemDetalhado(BaseModel):
    id: uuid.UUID
    ingredient_id: uuid.UUID
    ingredient_nome: str
    quantidade: float
    unidade_base: str
    custo_item_centavos: int


class RecipeOut(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    nome: str
    tempo_preparo_minutos: float | None
    ativo: bool
    criado_em: datetime
    itens: list[RecipeItemDetalhado]
    custo_ingredientes_centavos: int
    custo_mao_de_obra_centavos: int
    custo_total_centavos: int


# ---------------------------------------------------------------------------
# Product (Fase 2 — Produto)
# ---------------------------------------------------------------------------

class ProductCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    tipo: TipoProduto = TipoProduto.simples
    recipe_id: uuid.UUID | None = Field(default=None, description="Obrigatório se tipo=simples; deve ficar vazio se tipo=combo")
    unidade_venda: UnidadeVenda = UnidadeVenda.un
    embalagem_centavos: int = Field(default=0, ge=0)


class ProductUpdate(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=200)
    unidade_venda: UnidadeVenda | None = None
    embalagem_centavos: int | None = Field(default=None, ge=0)


class ComboItemDetalhado(BaseModel):
    id: uuid.UUID
    component_product_id: uuid.UUID
    component_nome: str
    quantidade: float
    custo_unitario_centavos: int
    custo_item_centavos: int


class PizzaSaborDetalhado(BaseModel):
    id: uuid.UUID
    sabor_product_id: uuid.UUID
    sabor_nome: str
    fracao: float
    custo_contribuido_centavos: int


class ProductOut(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    tipo: str
    recipe_id: uuid.UUID | None
    nome: str
    unidade_venda: UnidadeVenda
    embalagem_centavos: int
    estado: str
    criado_em: datetime
    itens: list[RecipeItemDetalhado]
    itens_combo: list[ComboItemDetalhado]
    itens_pizza: list[PizzaSaborDetalhado]
    custo_ingredientes_centavos: int
    custo_mao_de_obra_centavos: int
    custo_componentes_centavos: int
    custo_base_pizza_centavos: int
    custo_sabores_centavos: int
    custo_total_centavos: int  # da ficha técnica sozinha (ingredientes + mão de obra) -- 0 para combo/pizza
    custo_total_do_item_centavos: int  # número final, qualquer que seja o tipo


class ComboItemCreate(BaseModel):
    component_product_id: uuid.UUID
    quantidade: float = Field(gt=0, default=1)


class PizzaSaborCreate(BaseModel):
    sabor_product_id: uuid.UUID
    fracao: float = Field(gt=0, le=1, description="Ex: 0.5 para metade da pizza")


# ---------------------------------------------------------------------------
# SalesChannel (Fase 2 — Canal de Venda)
# ---------------------------------------------------------------------------

class SalesChannelCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    taxa_percentual: float = Field(default=0, ge=0, lt=100)
    taxa_fixa_centavos: int = Field(default=0, ge=0)
    imposto_override_percentual: float | None = Field(default=None, ge=0, lt=100)


class SalesChannelUpdate(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=200)
    taxa_percentual: float | None = Field(default=None, ge=0, lt=100)
    taxa_fixa_centavos: int | None = Field(default=None, ge=0)
    imposto_override_percentual: float | None = Field(default=None, ge=0, lt=100)


class SalesChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    nome: str
    taxa_percentual: float
    taxa_fixa_centavos: int
    imposto_override_percentual: float | None
    ativo: bool
    criado_em: datetime


# ---------------------------------------------------------------------------
# ProductChannelPricing (Fase 2 — Precificação)
# ---------------------------------------------------------------------------

class PricingCreate(BaseModel):
    channel_id: uuid.UUID
    margem_desejada_percentual: float = Field(ge=0, lt=100)
    preco_manual_centavos: int | None = Field(default=None, ge=0, description="Preço Estratégico, opcional")


class PricingUpdate(BaseModel):
    margem_desejada_percentual: float | None = Field(default=None, ge=0, lt=100)
    preco_manual_centavos: int | None = Field(default=None, ge=0)


class PricingOut(BaseModel):
    product_id: uuid.UUID
    channel_id: uuid.UUID
    custo_total_do_item_centavos: int
    taxa_percentual_aplicada: float
    taxa_fixa_centavos: int
    imposto_percentual_aplicado: float
    margem_desejada_percentual: float
    preco_recomendado_centavos: int
    preco_minimo_centavos: int
    preco_manual_centavos: int | None
    preco_em_vigor_centavos: int
    origem_do_preco: str
    preco_redondo_sugerido_centavos: int
    mc_centavos: int
    mc_percentual: float | None
    abaixo_do_preco_minimo: bool


# ---------------------------------------------------------------------------
# Sale (Fase 2 — Registrar Venda)
# ---------------------------------------------------------------------------

class SaleCreate(BaseModel):
    product_id: uuid.UUID
    channel_id: uuid.UUID
    quantidade: float = Field(gt=0)
    usar_preco_redondo: bool = False
    idempotency_key: str | None = Field(default=None, max_length=200)


class SaleItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    quantidade: float
    preco_tabela_centavos: int
    desconto_bancado_estabelecimento_centavos: int
    desconto_subsidiado_canal_centavos: int
    promotion_id: uuid.UUID | None
    preco_unitario_praticado_centavos: int
    custo_total_do_item_centavos: int
    civ_centavos: int
    embalagem_centavos: int
    mao_de_obra_centavos: int
    taxa_percentual_canal: float
    taxa_fixa_canal_centavos: int
    imposto_percentual: float
    margem_contribuicao_unitaria_centavos: int
    margem_contribuicao_total_centavos: int
    margem_contribuicao_percentual: float
    origem_preco_tipo: str
    foi_arredondado: bool
    preco_antes_do_arredondamento_centavos: int | None


class SaleOut(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    channel_id: uuid.UUID
    financial_period_id: uuid.UUID
    status: str
    data_hora_ocorrencia: datetime
    data_hora_registro: datetime
    item: SaleItemOut


# ---------------------------------------------------------------------------
# PartialReturn (Fase 2 — Devolução Parcial)
# ---------------------------------------------------------------------------

class PartialReturnCreate(BaseModel):
    quantidade_devolvida: float = Field(gt=0)
    motivo: str = Field(min_length=1, max_length=500)


class PartialReturnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sale_item_id: uuid.UUID
    quantidade_devolvida: float
    motivo: str
    criado_em: datetime


# ---------------------------------------------------------------------------
# Promotion (Fase 2 — Promoções)
# ---------------------------------------------------------------------------

class PromotionCreate(BaseModel):
    product_id: uuid.UUID
    channel_id: uuid.UUID
    nome: str = Field(min_length=1, max_length=200)
    tipo_desconto: TipoDesconto
    desconto_percentual: float | None = Field(default=None, gt=0, le=100)
    desconto_fixo_centavos: int | None = Field(default=None, gt=0)
    percentual_canal: float = Field(default=0, ge=0, le=100)
    subsidio_maximo_centavos: int | None = Field(default=None, ge=0)
    vigente_desde: datetime | None = None
    vigente_ate: datetime | None = None


class PromotionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    channel_id: uuid.UUID
    nome: str
    tipo_desconto: str
    desconto_percentual: float | None
    desconto_fixo_centavos: int | None
    percentual_canal: float
    subsidio_maximo_centavos: int | None
    vigente_desde: datetime
    vigente_ate: datetime | None
    ativo: bool
    criado_em: datetime


# ---------------------------------------------------------------------------
# FixedCost (Fase 2 — Custo Fixo)
# ---------------------------------------------------------------------------

class FixedCostCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    valor_mensal_centavos: int = Field(gt=0)


class FixedCostUpdate(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=200)
    valor_mensal_centavos: int | None = Field(default=None, gt=0)


class FixedCostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    nome: str
    valor_mensal_centavos: int
    ativo: bool
    criado_em: datetime


# ---------------------------------------------------------------------------
# Expense (Fase 2 — Despesa)
# ---------------------------------------------------------------------------

class ExpenseCreate(BaseModel):
    tipo: TipoDespesa
    nome: str = Field(min_length=1, max_length=200)
    valor_centavos: int = Field(gt=0)


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    financial_period_id: uuid.UUID
    tipo: str
    nome: str
    valor_centavos: int
    data: datetime


# ---------------------------------------------------------------------------
# Resultado do Período (Fase 2 — Fechamento/Relatórios)
# ---------------------------------------------------------------------------

class ResultadoPeriodoOut(BaseModel):
    financial_period_id: uuid.UUID
    status_periodo: str
    quantidade_vendas: int
    faturamento_bruto_centavos: int
    descontos_bancados_centavos: int
    faturamento_liquido_centavos: int
    civ_centavos: int
    margem_bruta_centavos: int
    embalagem_centavos: int
    mao_de_obra_centavos: int
    taxa_fixa_canal_centavos: int
    comissao_mais_imposto_venda_centavos: int
    margem_contribuicao_centavos: int
    custo_fixo_periodo_centavos: int
    resultado_operacional_centavos: int
    despesas_financeiras_centavos: int
    despesas_nao_operacionais_centavos: int
    lucro_antes_imposto_centavos: int
    imposto_lucro_centavos: int
    lucro_liquido_centavos: int


class ProdutoRentavelOut(BaseModel):
    product_id: uuid.UUID
    product_nome: str
    quantidade_vendida: float
    faturamento_centavos: int
    margem_contribuicao_total_centavos: int


# ---------------------------------------------------------------------------
# Movimentos manuais de estoque (Fase 2 — Perda, Consumo Interno, Ajuste)
# ---------------------------------------------------------------------------

class RegistrarPerdaRequest(BaseModel):
    quantidade: float = Field(gt=0, description="Na unidade-base do insumo (g, ml ou un)")
    nota: str = Field(min_length=1, max_length=500)


class RegistrarConsumoInternoRequest(BaseModel):
    quantidade: float = Field(gt=0)
    nota: str = Field(min_length=1, max_length=500)


class RegistrarAjusteRequest(BaseModel):
    novo_saldo: float = Field(ge=0, description="O valor ABSOLUTO da contagem física, na unidade-base")
    nota: str = Field(min_length=1, max_length=500, description="Obrigatória — por que o saldo está sendo corrigido")


class InventoryMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ingredient_id: uuid.UUID
    tipo: str
    qtd: float
    origem: str
    data: datetime
    nota: str | None
    estoque_resultante: float
    status: str
