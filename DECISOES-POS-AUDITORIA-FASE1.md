# Decisões Registradas — Pós-Auditoria Forense da Fase 1 (Comando 12)

Este documento existe exclusivamente para registrar, por escrito, as decisões arquiteturais e pendências identificadas na Auditoria Forense (Comando 11) — conforme exigido pelo Comando 12, seção 13.

---

## Decisão 1 — Cardinalidade User ↔ Business

```
User → 1 Business
Business → N Users
```

Um usuário pertence a exatamente um negócio. Um negócio pode ter vários usuários. Não existe (nem existirá nesta versão) tabela de associação N:N entre `User` e `Business`. RBAC não é implementado nesta fase — todo usuário autenticado de um negócio tem acesso igual às operações desse negócio.

**Esta é a decisão oficial para o MVP atual — não uma limitação permanente da plataforma.** A arquitetura futura poderá evoluir para suporte a múltiplos negócios por usuário caso isso seja necessário em versões posteriores (por exemplo, um contador ou consultor que atenda vários estabelecimentos). Essa evolução, se vier a ocorrer, exigirá uma tabela de associação própria e uma revisão do mecanismo de token — não foi implementada, nem antecipada, nem bloqueada por nada do que existe hoje.

**Classificação:** decisão de implementação (não uma exigência textual explícita do Contrato Técnico 08/08-B), agora ratificada conscientemente para o MVP.

---

## Decisão 2 — Validação de Timezone

`Business.timezone` deve ser um identificador IANA válido, verificado contra `zoneinfo.available_timezones()` (biblioteca padrão do Python — nenhuma dependência externa adicionada). Implementado como `field_validator` em `SignupRequest` (`app/schemas.py`) — o único ponto de entrada que hoje grava esse campo.

Não altera timestamps existentes, não altera a política de UTC já vigente, não altera `FinancialPeriod`, não altera nenhuma regra financeira.

---

## Pendências Futuras (registradas, não implementadas — por decisão explícita do Comando 12)

| # | Item | Decisão do Comando 12 |
|---|---|---|
| 1 | `revoked_tokens` sem expurgo automático | **Não implementar agora.** A tabela deverá possuir política de limpeza/expiração antes da entrada em produção real em escala. Nenhuma infraestrutura (cron/worker/scheduler/TTL) foi criada neste comando. |
| 2 | `python-jose` como dependência de JWT | **Não migrar agora.** Item de revisão de segurança antes da produção — a preocupação é preventiva, não uma vulnerabilidade confirmada na versão instalada. |
| 3 | Armazenamento do token no frontend (`localStorage`) | **Não alterar agora.** A tela atual é uma interface de validação mínima, não o frontend final. A estratégia definitiva de armazenamento/autorização do token deverá ser revisada quando o frontend de produção for construído. |

---

## O Que Foi Efetivamente Alterado Neste Comando

1. `app/schemas.py` — validação de timezone IANA via `zoneinfo` (stdlib).
2. `app/services/business.py` — 3 novas funções (`get_business_by_id`, `get_operation_config`, `update_operation_config`), estendendo o serviço já existente.
3. `app/routers/business.py` — reescrito para delegar 100% ao serviço; nenhum `db.query`/`db.get` direto restante.
4. `tests/test_timezone.py` — 6 novos testes (os 5 casos exatos pedidos + UTC puro).
5. `tests/test_business_service_layer.py` — novo arquivo, 6 testes confirmando a padronização sem regressão de contrato HTTP ou de isolamento multi-tenant.

**Nenhuma migração foi criada** — confirmado por `alembic revision --autogenerate`, que gerou uma migração vazia (`pass`), depois descartada por não representar nenhuma mudança real de schema.

**Nenhuma entidade, tabela, model, schema, endpoint ou regra da Fase 2 foi criada ou antecipada** — reconfirmado por escaneamento de escopo idêntico ao da Auditoria Forense, sem nenhuma nova ocorrência fora de comentário/docstring.
