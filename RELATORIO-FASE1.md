# Relatório Técnico — Fase 1 (Banco + Auth + Base + FinancialPeriod mínimo)

**Status: Fase 1 concluída, testada e validada de ponta a ponta contra infraestrutura real (não simulada). Código em `/home/claude/hamburgueria-fase1/`.**

> **Atualização (Comando 12):** este relatório documenta o estado da Fase 1 tal como aprovado pela Auditoria Forense (Comando 11, veredito 🟡 Aprovado com Ressalvas). As pendências levantadas naquela auditoria (validação de timezone e camada de serviço de `business.py`) foram fechadas no Comando 12 — ver `DECISOES-POS-AUDITORIA-FASE1.md` para o registro completo das decisões (incluindo a cardinalidade User↔Business, agora ratificada oficialmente) e das pendências conscientemente adiadas (expurgo de `revoked_tokens`, revisão de `python-jose`, estratégia definitiva de token no frontend).

---

## A. Stack Utilizada

| Camada | Escolha | Por quê |
|---|---|---|
| Banco de dados | **PostgreSQL 16** (instalado via `apt`, real, rodando) | Único banco entre as opções do ambiente com suporte nativo a índice único **parcial** (`WHERE data_hora_fim IS NULL`) — a constraint mais crítica desta fase. Não foi escolhido "por preferência": SQLite também suportaria parcialmente, mas MVCC/locking de linha do Postgres é o modelo de concorrência que a Especificação v1.3 §20.7 pressupõe |
| Backend | **Python 3.12 + FastAPI 0.141** | Tipagem, injeção de dependência nativa (usada para o isolamento multi-tenant — ver seção F), geração automática de OpenAPI/Swagger |
| ORM | **SQLAlchemy 2.0** | Controle explícito sobre `UPDATE ... RETURNING` (necessário para o mecanismo de fechamento) e sobre constraints/índices customizados |
| Migrações | **Alembic** | Versionadas, reproduzíveis — testado em banco novo do zero (seção C) |
| Autenticação | **bcrypt** (direto, sem passlib — ver Desvios) + **JWT (python-jose)** | Hash de senha padrão de mercado; token stateless com suporte a revogação real (tabela `revoked_tokens`) |
| Testes | **pytest + FastAPI TestClient**, contra um banco Postgres de teste real (não mockado) | Constraints de banco só se provam contra um banco de verdade |
| Frontend | HTML + JS puro, sem framework/build step | Explicitamente pedido como mínimo, não dashboard |

Nenhum banco foi escolhido "só por preferência" (Comando 10, Parte 26): a escolha do Postgres foi validada tecnicamente antes de decidir (verifiquei suporte a índice parcial, testei o `gen_random_uuid()` nativo do PG16 sem extensão).

---

## B. Estrutura Criada (todas as tabelas)

| Tabela | Propósito |
|---|---|
| `businesses` | Raiz multi-tenant |
| `users` | Autenticação — 1 usuário pertence a exatamente 1 negócio nesta fase (RBAC fora de escopo) |
| `operation_configs` | Configuração de regra de negócio, 1:1 com `businesses` |
| `financial_periods` | O núcleo desta fase — abertura/fechamento com garantia de banco |
| `idempotency_records` | Suporte a idempotência (§1.24 do Contrato Técnico) |
| `revoked_tokens` | Suporte a logout real com JWT stateless |

Nenhuma entidade das fases seguintes (`Ingredient`, `Product`, `Sale` etc.) foi criada — meta explícita do Comando 10 respeitada.

---

## C. Migrações

Uma única migração até aqui: `9e18fe9166d9_fase1_base_business_auth_financial_period.py`.

**Reprodutibilidade testada de verdade:** apliquei a mesma migração em dois bancos distintos criados do zero (`hamburgueria_fase1` e `hamburgueria_fase1_test`) e confirmei que ambos chegam à estrutura idêntica — não é uma alegação, é um resultado verificado nesta sessão.

---

## D. Constraints (todas, extraídas diretamente do banco via `pg_constraint`)

| Tabela | Constraint | Tipo |
|---|---|---|
| `operation_configs` | `uq_operation_config_business` | UNIQUE(business_id) — garante o 1:1 real |
| `idempotency_records` | `uq_idempotency_business_key` | UNIQUE(business_id, idempotency_key) |
| `users` → `businesses` | `users_business_id_fkey` | FK, **ON DELETE RESTRICT** |
| `operation_configs` → `businesses` | `operation_configs_business_id_fkey` | FK, ON DELETE RESTRICT |
| `idempotency_records` → `businesses` | idem | FK, ON DELETE RESTRICT |
| `financial_periods` → `businesses` | `financial_periods_business_id_fkey` | FK, ON DELETE RESTRICT |
| `financial_periods` → `users` | `financial_periods_criado_por_user_id_fkey` | FK, ON DELETE RESTRICT |

**Nenhuma FK usa `CASCADE`** — confirmado linha a linha acima, exatamente como o Contrato Técnico exige (§1.25): nenhuma exclusão pode destruir histórico silenciosamente.

---

## E. Índices (todos, extraídos via `pg_indexes`)

| Índice | Definição |
|---|---|
| **`uq_financial_period_one_open_per_business`** | `UNIQUE (business_id) WHERE (data_hora_fim IS NULL)` — **a constraint mais importante desta fase**, confirmada existindo de verdade no banco |
| `uq_operation_config_business` | UNIQUE(business_id) |
| `uq_idempotency_business_key` | UNIQUE(business_id, idempotency_key) |
| `ix_users_email` | UNIQUE(email) — um e-mail, uma conta, globalmente |
| `ix_users_business_id`, `ix_financial_periods_business_id` | Índices simples de FK, para performance de filtro por negócio |

---

## F. Segurança — Como o Isolamento Multi-Tenant é Garantido

**Mecanismo, não promessa:** toda rota que acessa dado de negócio depende de `get_current_business_id` (`app/deps.py`), que **só** extrai `business_id` do payload assinado do JWT — nunca de um parâmetro de rota, query string ou corpo de requisição. Não existe, em nenhum lugar do código, uma rota que aceite `business_id` vindo do cliente para decidir o que consultar.

Testado e comprovado (`tests/test_multi_tenant.py`, 4 testes, todos passando): Business A não consegue ler o `Business`, `OperationConfig` ou `FinancialPeriod` de Business B, mesmo tentando fechar o período de B pelo endpoint de A — o fechamento de A afeta exclusivamente o período de A.

---

## G. FinancialPeriod — Como Cada Peça Funciona

- **Identificação do período aberto:** `SELECT ... WHERE business_id = X AND data_hora_fim IS NULL` — sempre no máximo 1 resultado, garantido pelo índice único parcial (seção E), não só pela lógica da aplicação.
- **Fechamento:** `UPDATE financial_periods SET data_hora_fim = agora WHERE business_id = X AND data_hora_fim IS NULL RETURNING id`, seguido da criação do próximo período, **na mesma transação**.
- **Concorrência:** comprovada com um teste determinístico (`test_t09_fp01_colisao_real_de_lock_e_resolvida_corretamente`) que força duas transações a colidirem de verdade na mesma linha via `threading.Event` (não um `Barrier`, que se mostrou insuficiente — ver seção J, Desvios/Aprendizados). Resultado medido: a segunda transação **bloqueia por ~0,8s de verdade**, esperando o lock da primeira, e ao ser liberada encontra corretamente 0 linhas elegíveis (mecanismo EvalPlanQual do Postgres em READ COMMITTED).
- **Novo período:** criado automaticamente, sempre, na mesma transação do fechamento — nunca existe uma janela sem período aberto.

---

## H. Idempotência — Como Funciona

Tabela `idempotency_records` com `UNIQUE(business_id, idempotency_key)`. O serviço (`app/services/idempotency.py`) tenta gravar essa chave **antes** de processar a ação real; se a chave já existe, a operação real nunca é reexecutada — o resultado já gravado é devolvido. Testado com: reenvio simples, duas requisições genuinamente concorrentes com a mesma chave (via threads reais), e confirmação de que a mesma chave em dois negócios diferentes não conflita (4 testes, `tests/test_idempotency.py`).

---

## I. Testes — Resultado Completo

**28 de 28 testes passando, de forma estável (confirmado em 4 execuções consecutivas da suíte inteira).**

| Teste | Cenário | Resultado Esperado | Resultado Obtido | Status |
|---|---|---|---|---|
| `test_signup_cria_business_config_e_primeiro_periodo` | Signup completo | Business+Config+Período criados atomicamente | ✓ | PASS |
| `test_email_duplicado_e_rejeitado` | E-mail repetido | 409 | 409 | PASS |
| `test_login_com_credenciais_corretas` / `_senha_errada` | Login | 200 / 401 | 200 / 401 | PASS |
| `test_logout_revoga_o_token_de_verdade` | Logout | Token para de funcionar | Confirmado (401 após logout) | PASS |
| `test_operation_config_metodo_rateio_nao_e_editavel_via_api` | Tentativa de mudar método de rateio | Permanece `horas_produtivas` | Confirmado | PASS |
| `test_sem_token_e_rejeitado` | Sem Authorization header | 401/403 | 401 | PASS |
| **T09-MT01** (4 variações) | Business A acessando dado de B | Rejeitado/isolado | Confirmado nas 4 variações | PASS |
| **T09-ID01** a **ID04** | Idempotência (simples, concorrente, retry, cross-business) | Nunca duplica; cross-business permitido | Confirmado nos 4 casos | PASS |
| **T09-FP01** (colisão real) | Lock genuíno de linha | Bloqueio real + resolução correta | Bloqueou 0,8s, resolveu para 0 linhas | PASS |
| **T09-FP01b** | Fluxo completo via API concorrente | Nunca 2 períodos abertos | 1 período aberto confirmado no banco | PASS |
| **T09-FP02** | Operação futura + fechamento simultâneos | Nunca período nulo/inválido | Sempre resolvido para período válido | PASS |
| **T09-FP03** | 5 fechamentos concorrentes | Nunca mais de 1 aberto | 1 aberto, 2-6 períodos totais (dependendo do timing real) | PASS |
| **T09-IMM01** (2 variações) | Período fechado nunca muda | Byte-a-byte idêntico depois de novas operações | Confirmado | PASS |
| Rollback (2 testes) | Falha no meio de uma transação | Nada parcialmente persistido | Confirmado (nenhum registro órfão) | PASS |
| FK RESTRICT (2 testes) | Excluir Business/User referenciado | `IntegrityError` | Confirmado | PASS |
| Timezone (3 testes) | IANA armazenado, timestamps UTC-aware | Confirmado | Confirmado | PASS |

**Validação adicional fora da suíte automatizada:** rodei o servidor real (`uvicorn`) contra o banco de desenvolvimento e executei manualmente, via HTTP puro, o fluxo completo (signup → consultar business/config/período → fechar → reenviar o mesmo fechamento com a mesma chave de idempotência → logout → confirmar token revogado). Todas as 9 chamadas retornaram exatamente o esperado — log do servidor sem nenhum erro.

---

## J. Pendências

| Item | Classificação |
|---|---|
| Nenhuma pendência crítica, alta ou média identificada nesta fase | — |
| RBAC completo | ⚪ Conscientemente fora de escopo (Comando 09/10) — `criadoPorUserId` já presente em `financial_periods` para não exigir retrofitting depois |
| Rate limiting / proteção contra força bruta no login | 🟢 BAIXA — não fazia parte do escopo da Fase 1, mas vale registrar para uma fase de segurança futura |
| Refresh token (hoje o JWT expira em 24h sem renovação) | 🟢 BAIXA — suficiente para validar a fundação; um fluxo de refresh pode ser adicionado sem quebrar o formato atual |

---

## K. Desvios do Contrato Técnico

```
DESVIOS DO CONTRATO TÉCNICO: NENHUM DE REGRA DE NEGÓCIO.
```

Dois ajustes **técnicos**, sem impacto em nenhuma regra de negócio, precisam ser registrados com transparência:

1. **`passlib` foi trocado por `bcrypt` direto.** O contrato técnico não especificava a biblioteca exata de hashing — só a política ("hash de senha", já implícita na arquitetura). Durante a implementação, `passlib` se mostrou incompatível com a versão atual do pacote `bcrypt` (bug conhecido de detecção de versão, `passlib` tenta ler um atributo que não existe mais no `bcrypt` 4.x/5.x). Troquei para usar `bcrypt` diretamente — mesma política de segurança (hash com salt, bcrypt), sem a camada intermediária frágil. Nenhuma regra de negócio ou de segurança foi alterada.

2. **Metodologia de teste de concorrência corrigida durante a implementação.** Meus primeiros testes de "dois fechamentos simultâneos" usavam `threading.Barrier`, que sincroniza só o *início* de duas threads — não garante que elas de fato colidam na mesma linha do banco antes de uma completar. Isso produziu falsos alarmes (dois "vencedores" que, na verdade, eram dois fechamentos *sequenciais* legítimos, não uma corrida real). Troquei para sincronização determinística via `threading.Event`, que força a colisão de verdade e prova o mecanismo do Postgres corretamente. **Isso não é um desvio do contrato — é uma correção de rigor no próprio processo de teste**, registrada aqui porque a transparência sobre isso é mais importante do que esconder que aconteceu.

---

## Comandos para Reproduzir

```bash
cd hamburgueria-fase1
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
# configurar .env a partir do .env.example
./venv/bin/alembic upgrade head
./venv/bin/uvicorn app.main:app --reload
# em outro terminal, com um banco de teste separado configurado:
./venv/bin/pytest tests/ -v
```

---

**PARE — Fase 1 concluída conforme escopo. Fase 2 (Ingredientes/Fornecedores/Compras/Receitas) não foi iniciada, conforme instruído. Aguardando validação antes de prosseguir.**
