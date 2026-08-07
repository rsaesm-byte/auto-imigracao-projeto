# Migrations (Alembic)

Adotado em 2026-08-06 (Fase 0 da reforma do CRM) para substituir, daqui
pra frente, o padrão anterior de `_ensure_*_column()` hand-rolled em
`app/__init__.py`. Esse padrão antigo continua funcionando e **não foi
removido** (é seguro e ainda roda a cada boot) — mas só sabia adicionar
coluna nullable. Qualquer mudança de schema mais complexa (renomear
coluna, mudar tipo, mudar nullability, criar tabela nova relacionada)
deve virar uma migration Alembic daqui em diante.

## Como funciona neste projeto

`migrations/env.py` **não** tem uma URL de banco própria — ele importa
`engine` e `Base` direto de `app/db.py`, e importa os módulos de modelo
(`app.models`, `app.crm_models`, `app.crm_financial_models`,
`app.planner_models`) para popular `Base.metadata`. Ou seja, a Alembic
sempre olha para o mesmo `instance/app.db` que a aplicação usa — não há
`alembic.ini` com URL duplicada para divergir.

`render_as_batch=True` está sempre ligado: no SQLite, `ALTER TABLE`
nativo só suporta `ADD COLUMN`. Qualquer outra operação (rename, mudar
tipo, dropar coluna, mudar constraint) precisa do modo batch do Alembic,
que recria a tabela por trás dos panos preservando os dados.

## Workflow para uma mudança de schema nova

1. Alterar o(s) modelo(s) em `app/crm_models.py` (ou onde for).
2. Fazer backup manual antes de gerar/rodar a migration:
   ```
   python -c "from app.services.db_backup import backup_database; backup_database('nome-da-mudanca')"
   ```
3. Gerar o rascunho:
   ```
   python -m alembic revision --autogenerate -m "descrição curta"
   ```
4. **Ler o arquivo gerado com atenção antes de rodar.** O autogenerate
   compara `Base.metadata` contra o banco real e pode sugerir
   `DROP COLUMN`/`DROP TABLE` para qualquer coisa que exista no banco mas
   não esteja mapeada no ORM (ex.: colunas adicionadas por scripts fora
   do SQLAlchemy, como `notion_page_id` — ver comentário na baseline
   `4182fc577a23`). Nunca aceitar um `DROP` sem confirmar que é
   intencional.
5. Rodar: `python -m alembic upgrade head`.
6. Se algo der errado: `python -m alembic downgrade -1` (a migration
   precisa ter um `downgrade()` correto — não deixar o boilerplate
   `pass` se a operação não for realmente reversível sem perda).

## Baseline (revisão `4182fc577a23`)

É um no-op deliberado — não altera nada, só marca "a partir daqui,
mudanças de schema passam por migration revisada". O diff real entre
modelo e banco na época da adoção (colunas `notion_page_id` fora do ORM,
alguns índices/NOT NULL não declarados formalmente) foi documentado no
próprio arquivo da migration, não corrigido às pressas.
