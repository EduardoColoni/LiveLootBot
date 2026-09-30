# Migrações

Schema do banco versionado. **Nenhum destes arquivos roda sozinho** — são aplicados à mão,
pelo DBeaver ou pelo `psql`.

## Criar o banco do zero

```bash
createdb -U postgres live_loot_bot_test
psql -U postgres -d live_loot_bot_test -f migrations/000_schema_inicial.sql
```

O `000_schema_inicial.sql` é o **estado atual completo**: tipos, tabelas, sequences,
constraints, índices e as funções `insert_items` e `make_raffle`. Não cria o banco em si e
não contém dados.

Se o Postgres subir pelo Docker, o arquivo pode ser montado em
`/docker-entrypoint-initdb.d/` — o contêiner o executa automaticamente na primeira criação
do volume, contra o banco indicado em `POSTGRES_DB`.

## Alterações futuras

Arquivos numerados em ordem, aplicados por cima do baseline:

```
001_descricao_curta.sql
002_outra_coisa.sql
```

Quando forem muitos, vale regerar o baseline a partir do banco e recomeçar a numeração:

```bash
pg_dump -U postgres -d live_loot_bot_test --schema-only --no-owner --no-privileges \
  > migrations/000_schema_inicial.sql
```

Os `--no-owner --no-privileges` são necessários: sem eles o dump carrega `ALTER ... OWNER TO`
e referências a roles que podem não existir em outra máquina. Se estiver usando um `pg_dump`
recente, remova as linhas `\restrict` e `\unrestrict` do arquivo gerado — são meta-comandos
que só o `psql` novo entende e que quebram no DBeaver.

## `historico/`

Migrações **já refletidas no baseline**. Servem apenas para atualizar um banco antigo que
ainda não passou por elas; num banco criado pelo `000` são desnecessárias (e inofensivas,
porque usam `IF EXISTS`).

- `2026-09_remove_kick.sql` — remove a tabela e as colunas da integração com a Kick.
  **A ordem dos passos importa**: existe uma foreign key de
  `kick_eventsub_subscriptions.platform_id` para `streamer_platform.platform_id`, então a
  tabela precisa ser removida antes das linhas.

## O que não entra aqui

Dados. A tabela `authenticated_users` guarda identificadores de Discord e Twitch de pessoas
reais, e a `streamer_platform` guarda tokens de acesso. Versione só a estrutura.
