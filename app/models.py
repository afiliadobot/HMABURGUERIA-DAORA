"""
Modelos SQLAlchemy — Fase 1.

Toda entidade aqui segue as Convenções Globais do Contrato Técnico (§1):
- id: UUID gerado no servidor (gen_random_uuid() do Postgres), nunca pelo cliente.
- businessId denormalizado onde a entidade pertence a um negócio.
- Constraints reais de banco (UNIQUE, índice único parcial, FK com ON DELETE RESTRICT)
  em vez de invariantes só verificadas pela aplicação.
- Dinheiro sempre BigInteger (centavos, inteiro) — nunca Float/Numeric para valores monetários.
- Quantidade física sempre Numeric(precision, 3) quando existir nesta fase.

Esta fase (1) implementa: Business, User, OperationConfig, FinancialPeriod,
IdempotencyRecord, RevokedToken. A partir daqui, a Fase 2 começa a adicionar
entidades de domínio, uma de cada vez, sempre com autorização prévia — a
primeira é `Ingredient` (cadastro básico de insumo, sem preço/estoque ainda).
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    BigInteger,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid_col(primary_key: bool = False):
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=primary_key,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )


# ---------------------------------------------------------------------------
# Enums — espelham exatamente os enums do Contrato Técnico (§1), nunca livres.
# ---------------------------------------------------------------------------

class Segmento(str, enum.Enum):
    hamburgueria = "hamburgueria"
    pizzaria = "pizzaria"
    lanchonete = "lanchonete"
    restaurante = "restaurante"
    delivery = "delivery"
    dark_kitchen = "dark_kitchen"
    cafeteria = "cafeteria"
    acaiteria = "acaiteria"
    confeitaria = "confeitaria"
    marmitaria = "marmitaria"
    food_truck = "food_truck"
    pastelaria = "pastelaria"
    sorveteria = "sorveteria"
    outro = "outro"


class MetodoRateio(str, enum.Enum):
    horas_produtivas = "horas_produtivas"  # único método aprovado (Decisão 01, Comando 03-B) — não substituir


class ModoProporcionalizacaoFixo(str, enum.Enum):
    mes_cheio = "mes_cheio"
    proporcional_dias = "proporcional_dias"


class BaseComissao(str, enum.Enum):
    valor_reconhecido_estabelecimento = "valor_reconhecido_estabelecimento"
    valor_pago_cliente = "valor_pago_cliente"


class UnidadeCompra(str, enum.Enum):
    """Unidade em que o insumo é comprado. kg/g e L/ml são convertíveis entre si
    (mesma categoria); 'un' nunca é convertível para nenhuma das outras — essa
    regra de fronteira já foi decidida e vale para todas as fases futuras."""
    kg = "kg"
    g = "g"
    L = "L"
    ml = "ml"
    un = "un"


# Fator de conversão de cada unidade de compra para sua unidade-base (a mais fina
# da mesma categoria: kg->g, L->ml, g/ml/un permanecem 1:1). Centralizado aqui —
# nenhum outro lugar do código deve reimplementar essa tabela.
FATOR_CONVERSAO_PARA_BASE = {
    UnidadeCompra.kg: 1000,
    UnidadeCompra.g: 1,
    UnidadeCompra.L: 1000,
    UnidadeCompra.ml: 1,
    UnidadeCompra.un: 1,
}

# Rótulo da unidade-base correspondente a cada unidade de compra — usado em
# toda exibição de estoque/custo por unidade-base (nunca a unidade de compra).
UNIDADE_BASE_LABEL = {
    UnidadeCompra.kg: "g",
    UnidadeCompra.g: "g",
    UnidadeCompra.L: "ml",
    UnidadeCompra.ml: "ml",
    UnidadeCompra.un: "un",
}


class OrigemPreco(str, enum.Enum):
    manual = "manual"
    compra = "compra"  # reservado para quando o módulo de Compras existir


class TipoMovimento(str, enum.Enum):
    """Só 'entrada' está ativo nesta etapa (gerada por Compra). Os demais tipos
    já existem no enum para não exigir uma nova migração quando forem ligados
    em fases futuras (Venda, Perda, Consumo Interno, Ajuste)."""
    entrada = "entrada"
    saida_venda = "saida_venda"
    perda = "perda"
    consumo_interno = "consumo_interno"
    ajuste = "ajuste"


class OrigemMovimento(str, enum.Enum):
    compra = "compra"
    venda = "venda"
    cancelamento = "cancelamento"
    devolucao_parcial = "devolucao_parcial"
    manual = "manual"


class StatusMovimento(str, enum.Enum):
    ativo = "ativo"
    cancelado = "cancelado"  # 'ajuste' nunca pode ir para este estado (regra já registrada)


class UnidadeVenda(str, enum.Enum):
    un = "un"
    kg = "kg"
    g = "g"
    L = "L"
    ml = "ml"


class TipoProduto(str, enum.Enum):
    simples = "simples"
    combo = "combo"
    pizza_fracionada = "pizza_fracionada"


class EstadoProduto(str, enum.Enum):
    ativo = "ativo"
    arquivado = "arquivado"
    # Nunca escolhido manualmente — o sistema marca sozinho quando a ficha
    # técnica usada por este produto é arquivada (mesma regra já usada para
    # Combo/Pizza na especificação: nunca recalcula removendo em silêncio,
    # sempre sinaliza pra revisão humana).
    precisa_revisao = "precisa_revisao"


class StatusVenda(str, enum.Enum):
    confirmada = "confirmada"
    cancelada = "cancelada"  # única transição permitida: confirmada -> cancelada, nunca o inverso


class OrigemPrecoVenda(str, enum.Enum):
    """Espelha ProductChannelPricing no momento da venda. 'promocional' e
    'manual' ficam reservados para quando Promoções existir."""
    recomendado = "recomendado"
    estrategico = "estrategico"
    promocional = "promocional"


class TipoDesconto(str, enum.Enum):
    percentual = "percentual"
    valor_fixo = "valor_fixo"


class TipoDespesa(str, enum.Enum):
    financeira = "financeira"        # juros, taxas bancárias
    nao_operacional = "nao_operacional"  # despesas fora da operação normal


# ---------------------------------------------------------------------------
# Business — raiz de todo o sistema multi-tenant.
# ---------------------------------------------------------------------------

class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    segment: Mapped[Segmento] = mapped_column(Enum(Segmento, name="segmento_enum"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL", server_default="BRL")
    # IANA timezone — ex: "America/Sao_Paulo". Nunca timezone fixo global (Comando 09/10, §4).
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="business")
    operation_config: Mapped["OperationConfig"] = relationship(back_populates="business", uselist=False)


# ---------------------------------------------------------------------------
# User — autenticação. Um usuário pertence a exatamente um Business nesta fase
# (RBAC/múltiplos negócios por usuário fica fora de escopo — pendência consciente).
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    business: Mapped["Business"] = relationship(back_populates="users")


# ---------------------------------------------------------------------------
# OperationConfig — 1:1 com Business. UNIQUE(business_id) garante o 1:1 de verdade.
# ---------------------------------------------------------------------------

class OperationConfig(Base):
    __tablename__ = "operation_configs"
    __table_args__ = (UniqueConstraint("business_id", name="uq_operation_config_business"),)

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False
    )

    volume_mensal_estimado: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    imposto_percentual: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=6.0)
    custo_hora_funcionario_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    metodo_rateio: Mapped[MetodoRateio] = mapped_column(
        Enum(MetodoRateio, name="metodo_rateio_enum"), nullable=False, default=MetodoRateio.horas_produtivas
    )

    # Limiares da matriz de rentabilidade (§16 v1.3) — configuráveis, nunca hardcoded nos engines.
    # Padrões sugeridos oficialmente e respeitados aqui como default de cadastro:
    cmv_alvo_max: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=35.0)
    margem_alvo_alta: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=55.0)
    margem_alvo_baixa: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=35.0)
    margem_perigosa: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=5.0)
    contrib_alvo_alta: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=20.0)
    contrib_alvo_baixa: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=8.0)

    aliquota_imposto_lucro: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    modo_proporcionalizacao_fixo: Mapped[ModoProporcionalizacaoFixo] = mapped_column(
        Enum(ModoProporcionalizacaoFixo, name="modo_proporcionalizacao_enum"),
        nullable=False,
        default=ModoProporcionalizacaoFixo.mes_cheio,
    )
    dias_operacao_por_mes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alertar_taxa_zero: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    base_comissao_padrao: Mapped[BaseComissao] = mapped_column(
        Enum(BaseComissao, name="base_comissao_enum"),
        nullable=False,
        default=BaseComissao.valor_reconhecido_estabelecimento,
    )

    business: Mapped["Business"] = relationship(back_populates="operation_config")


# ---------------------------------------------------------------------------
# FinancialPeriod — o coração desta fase. Índice único parcial garante, no
# próprio banco, que nunca existam 0 nem 2+ períodos abertos por negócio.
# ---------------------------------------------------------------------------

class FinancialPeriod(Base):
    __tablename__ = "financial_periods"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    data_hora_inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # NULL = aberto. Write-once: uma vez preenchido, nunca mais editado (nenhum código de
    # aplicação neste projeto executa UPDATE em data_hora_fim além do fechamento oficial).
    data_hora_fim: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    criado_por_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        # A CONSTRAINT QUE MAIS IMPORTA NESTA FASE (Comando 09, Parte 3 / Gate G05):
        # no máximo 1 período aberto por negócio, garantido pelo PRÓPRIO BANCO —
        # não por um SELECT COUNT(...) antes do INSERT, que teria uma janela de corrida.
        Index(
            "uq_financial_period_one_open_per_business",
            "business_id",
            unique=True,
            postgresql_where=(data_hora_fim.is_(None)),
        ),
    )


# ---------------------------------------------------------------------------
# IdempotencyRecord — §1.24 do Contrato Técnico.
# ---------------------------------------------------------------------------

class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key", name="uq_idempotency_business_key"),
    )

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    result_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# RevokedToken — apoio a logout real com JWT stateless (sem isso, "logout" não
# faria nada no servidor — o token continuaria válido até expirar sozinho).
# ---------------------------------------------------------------------------

class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)  # JWT ID
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# Ingredient — Fase 2, primeira entidade de domínio. Cadastro básico apenas:
# nome, unidade de compra, perda no preparo, estoque mínimo. Preço (Ingredient-
# PriceSnapshot) e estoque real (InventoryMovement) entram em etapas seguintes,
# de propósito, para não misturar tudo de uma vez.
# ---------------------------------------------------------------------------

class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    unidade_compra: Mapped[UnidadeCompra] = mapped_column(Enum(UnidadeCompra, name="unidade_compra_enum"), nullable=False)
    # 0 a 89,99% — nunca 90%+ (evita denominador zero/negativo em cálculos futuros de custo).
    perda_percentual: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    # Quantidade física — 3 casas decimais, convenção já estabelecida no Contrato Técnico.
    estoque_minimo: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# IngredientPriceSnapshot — histórico de preço do insumo. NUNCA editado nem
# excluído: cada registro é um retrato congelado de "quanto custava naquele
# momento". O custo por unidade-base ainda NÃO desconta a perda (isso entra
# depois, no cálculo de custo de uma receita) — este número é só "quanto custa
# 1 grama/ml/unidade deste insumo, na compra".
# ---------------------------------------------------------------------------

class IngredientPriceSnapshot(Base):
    __tablename__ = "ingredient_price_snapshots"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    preco_pago_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantidade_comprada: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    # Única exceção documentada à regra "dinheiro = centavos inteiro": aqui é
    # centavos x 1000 (milicentavos), porque custo por grama pode ser fracionário
    # em centavos (ex: R$120/5kg = R$0,024/g). Continua sendo um INTEIRO — nunca
    # float — só numa escala mais fina. Decisão já registrada no Contrato Técnico.
    custo_por_base_milicentavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vigente_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    origem: Mapped[OrigemPreco] = mapped_column(Enum(OrigemPreco, name="origem_preco_enum"), nullable=False, default=OrigemPreco.manual)


# ---------------------------------------------------------------------------
# Supplier (Fornecedor) — cadastro básico, mesmo padrão do Ingredient.
# ---------------------------------------------------------------------------

class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    contato: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# Purchase / PurchaseItem — registrar uma compra já dá entrada automática no
# estoque e gera um novo IngredientPriceSnapshot por item (origem=compra).
# Nesta etapa, toda compra nasce "recebida" — não existe estado "pendente".
# ---------------------------------------------------------------------------

class Purchase(Base):
    __tablename__ = "purchases"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    data: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    frete_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    outros_custos_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PurchaseItem(Base):
    __tablename__ = "purchase_items"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    purchase_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantidade_comprada: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    preco_total_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Preenchido depois do rateio de frete/outros custos — é o valor que
    # efetivamente alimenta o IngredientPriceSnapshot gerado por este item.
    frete_alocado_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    outros_custos_alocado_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    price_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredient_price_snapshots.id", ondelete="RESTRICT"), nullable=False
    )


# ---------------------------------------------------------------------------
# InventoryMovement — o "livro" de movimentos de estoque. Nesta etapa, só o
# tipo 'entrada' (vindo de Compra) é realmente criado — os demais tipos vêm
# em fases futuras, reaproveitando esta mesma tabela e este mesmo algoritmo
# de saldo, sem precisar de nova migração estrutural.
# ---------------------------------------------------------------------------

class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tipo: Mapped[TipoMovimento] = mapped_column(Enum(TipoMovimento, name="tipo_movimento_enum"), nullable=False)
    # Para 'ajuste' (fase futura): valor ABSOLUTO do novo saldo. Para os demais
    # tipos (incluindo 'entrada', o único ativo agora): delta, sempre positivo
    # para entrada, negativo para saídas futuras.
    qtd: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    origem: Mapped[OrigemMovimento] = mapped_column(Enum(OrigemMovimento, name="origem_movimento_enum"), nullable=False)
    origem_purchase_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_items.id", ondelete="RESTRICT"), nullable=True
    )
    origem_sale_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sale_items.id", ondelete="RESTRICT"), nullable=True
    )
    data: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    nota: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Valor de AUDITORIA PONTUAL — nunca fonte de saldo (regra já estabelecida
    # e comprovada por teste: usar isso como "saldo atual" diverge silenciosamente
    # se um movimento anterior for cancelado depois).
    estoque_resultante: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    status: Mapped[StatusMovimento] = mapped_column(
        Enum(StatusMovimento, name="status_movimento_enum"), nullable=False, default=StatusMovimento.ativo
    )
    financial_period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_periods.id", ondelete="RESTRICT"), nullable=False
    )


# ---------------------------------------------------------------------------
# Recipe / RecipeItem — a Ficha Técnica. RecipeItem é mutável (você pode
# ajustar quantidade ou remover um insumo enquanto a receita está ativa) —
# diferente de IngredientPriceSnapshot/InventoryMovement, que são históricos
# e imutáveis. O custo nunca é salvo aqui: é sempre recalculado na hora, a
# partir do preço ATUAL de cada insumo.
# ---------------------------------------------------------------------------

class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    # Tempo de ATENÇÃO ATIVA do preparo (não o tempo total do processo) —
    # convenção já estabelecida: alimenta o custo de mão de obra direta.
    tempo_preparo_minutos: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RecipeItem(Base):
    __tablename__ = "recipe_items"
    __table_args__ = (UniqueConstraint("recipe_id", "ingredient_id", name="uq_recipe_item_ingredient"),)

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Sempre na unidade-base do insumo (g, ml ou un) — nunca na unidade de
    # compra (kg/L). Evita qualquer conversão escondida no meio da receita.
    quantidade: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)


# ---------------------------------------------------------------------------
# Product — o item que o cliente vê no cardápio. Usa exatamente uma Ficha
# Técnica (Combo/Pizza, que usariam várias ou nenhuma, ficam para uma etapa
# futura — por isso recipe_id é obrigatório aqui, não opcional).
# ---------------------------------------------------------------------------

class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Nulo quando tipo=combo (um combo não tem ficha técnica própria — o custo
    # vem da soma dos produtos que o compõem, ver ComboItem).
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    tipo: Mapped[TipoProduto] = mapped_column(Enum(TipoProduto, name="tipo_produto_enum"), nullable=False, default=TipoProduto.simples)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    unidade_venda: Mapped[UnidadeVenda] = mapped_column(
        Enum(UnidadeVenda, name="unidade_venda_enum"), nullable=False, default=UnidadeVenda.un
    )
    embalagem_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    estado: Mapped[EstadoProduto] = mapped_column(
        Enum(EstadoProduto, name="estado_produto_enum"), nullable=False, default=EstadoProduto.ativo
    )
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# SalesChannel — Canal de Venda (Presencial, Delivery Próprio, iFood...).
# ---------------------------------------------------------------------------

class SalesChannel(Base):
    __tablename__ = "sales_channels"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    taxa_percentual: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    taxa_fixa_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    imposto_override_percentual: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# ProductChannelPricing — a precificação de um Produto num Canal específico.
# Nunca guarda o preço calculado (Recomendado/Mínimo são sempre recalculados
# na hora) — só guarda o que é decisão do usuário: a margem desejada, e,
# opcionalmente, um preço definido manualmente (Preço Estratégico).
# ---------------------------------------------------------------------------

class ProductChannelPricing(Base):
    __tablename__ = "product_channel_pricings"
    __table_args__ = (UniqueConstraint("product_id", "channel_id", name="uq_pricing_product_channel"),)

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_channels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    margem_desejada_percentual: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    # Preço Estratégico: definido manualmente pelo usuário. Quando presente,
    # é o preço "em vigor" — mas o Preço Recomendado continua sendo mostrado
    # ao lado, nunca escondido (regra já estabelecida: o sistema nunca finge
    # que um preço manual é o recomendado).
    preco_manual_centavos: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# Sale / SaleItem — o registro de que uma venda aconteceu de verdade. Tudo em
# SaleItem é congelado no momento da venda e NUNCA MAIS MUDA — é o coração da
# auditoria histórica de todo o sistema (regra estabelecida desde o início do
# projeto: uma alteração futura de preço/custo/taxa nunca pode alterar uma
# venda já registrada).
# ---------------------------------------------------------------------------

class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_channels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Write-once: atribuído no COMMIT, pelo período aberto naquele instante —
    # nunca pela data de ocorrência informada (regra §20.2 já estabelecida).
    financial_period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_periods.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[StatusVenda] = mapped_column(Enum(StatusVenda, name="status_venda_enum"), nullable=False, default=StatusVenda.confirmada)
    # Informativa — nunca decide o período financeiro (só data_hora_registro,
    # via financial_period_id, decide isso).
    data_hora_ocorrencia: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_hora_registro: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    criado_por_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class SaleItem(Base):
    __tablename__ = "sale_items"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sale_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Nesta versão, 1 Sale = exatamente 1 SaleItem (um produto por vez — um
    # pedido com vários produtos diferentes é registrado como vendas separadas).
    quantidade: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)

    # --- Tudo abaixo é congelado no momento da venda, valores POR UNIDADE
    # (exceto onde indicado como "total da venda") ---
    preco_tabela_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    desconto_bancado_estabelecimento_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    desconto_subsidiado_canal_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    promotion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("promotions.id", ondelete="RESTRICT"), nullable=True
    )
    preco_unitario_praticado_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    custo_total_do_item_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    civ_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    embalagem_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mao_de_obra_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    taxa_percentual_canal: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    # Taxa fixa é cobrada 1 VEZ por venda (pedido), nunca multiplicada pela
    # quantidade — por isso é um total da venda, não um valor por unidade.
    taxa_fixa_canal_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    imposto_percentual: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    margem_contribuicao_unitaria_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    margem_contribuicao_total_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    margem_contribuicao_percentual: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    origem_preco_tipo: Mapped[OrigemPrecoVenda] = mapped_column(Enum(OrigemPrecoVenda, name="origem_preco_venda_enum"), nullable=False)
    foi_arredondado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    preco_antes_do_arredondamento_centavos: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


# ---------------------------------------------------------------------------
# PartialReturn — devolução parcial de uma venda (diferente de cancelar a
# venda inteira). Sempre proporcional: devolve estoque e reconhece o estorno
# financeiro na fração exata devolvida, nunca a venda toda.
# ---------------------------------------------------------------------------

class PartialReturn(Base):
    __tablename__ = "partial_returns"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sale_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sale_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantidade_devolvida: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    motivo: Mapped[str] = mapped_column(String(500), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    criado_por_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


# ---------------------------------------------------------------------------
# ComboItem — os produtos que compõem um Product com tipo=combo. Detecção de
# ciclo obrigatória na escrita (Combo A não pode, direta ou indiretamente,
# conter a si mesmo através de outros combos).
# ---------------------------------------------------------------------------

class ComboItem(Base):
    __tablename__ = "combo_items"
    __table_args__ = (UniqueConstraint("combo_product_id", "component_product_id", name="uq_combo_item_component"),)

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    combo_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    component_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantidade: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=1)


# ---------------------------------------------------------------------------
# PizzaSabor — os sabores de um Product com tipo=pizza_fracionada. A base
# (massa, molho, embalagem) vem do recipe_id do próprio Product; cada sabor é
# uma FRAÇÃO adicional. sabor_product_id só pode apontar para tipo=simples —
# nunca outra pizza ou combo (evita recursão infinita, achado F5 já
# documentado desde o Contrato Técnico original).
# ---------------------------------------------------------------------------

class PizzaSabor(Base):
    __tablename__ = "pizza_sabores"
    __table_args__ = (UniqueConstraint("pizza_product_id", "sabor_product_id", name="uq_pizza_sabor"),)

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    pizza_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sabor_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    fracao: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)


# ---------------------------------------------------------------------------
# Promotion — desconto configurado para um Produto num Canal específico, com
# uma vigência e uma fração bancada pelo canal (subsídio, ex: iFood). Nunca
# aplicado retroativamente — só afeta vendas registradas DEPOIS de criada.
# ---------------------------------------------------------------------------

class Promotion(Base):
    __tablename__ = "promotions"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_channels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    tipo_desconto: Mapped[TipoDesconto] = mapped_column(Enum(TipoDesconto, name="tipo_desconto_enum"), nullable=False)
    desconto_percentual: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    desconto_fixo_centavos: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # % do desconto que o CANAL banca — o resto é sempre bancado pelo estabelecimento.
    percentual_canal: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    subsidio_maximo_centavos: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    vigente_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    vigente_ate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        # No máximo 1 promoção ATIVA por produto+canal — mesma garantia de
        # banco já usada em FinancialPeriod, evita ambiguidade sobre "qual
        # desconto vale" no momento da venda.
        Index(
            "uq_promotion_one_active_per_product_channel",
            "product_id", "channel_id",
            unique=True,
            postgresql_where=(ativo.is_(True)),
        ),
    )


# ---------------------------------------------------------------------------
# FixedCost — custo fixo mensal (aluguel, salários fixos, etc.). Entra no
# Resultado Operacional, rateado conforme OperationConfig.modo_proporcionalizacao_fixo.
# ---------------------------------------------------------------------------

class FixedCost(Base):
    __tablename__ = "fixed_costs"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    valor_mensal_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# Expense — despesa pontual (financeira ou não-operacional). Sempre vinculada
# ao período financeiro aberto no momento do registro — mesma regra de toda
# ação financeira do sistema.
# ---------------------------------------------------------------------------

class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    financial_period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_periods.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tipo: Mapped[TipoDespesa] = mapped_column(Enum(TipoDespesa, name="tipo_despesa_enum"), nullable=False)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    valor_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    data: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    criado_por_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
