# LiveLootBot

Sistema de sorteios automáticos durante transmissões ao vivo, integrando Discord e Twitch.
Projeto de TCC. Código, comentários e mensagens de commit em português.

A monografia descreve, em vários pontos, uma arquitetura **anterior** à atual — em especial o
fluxo de escolha do ganhador, que consultava a lista de espectadores do chat da Twitch. Ao
mexer no código, não tome o texto do TCC como especificação: as divergências estão mapeadas
e as pendências correspondentes listadas no fim deste arquivo.

## Como rodar

Tudo a partir da **raiz do projeto**, com o venv ativo.

Na primeira vez, crie os dois arquivos de configuração a partir dos modelos versionados:
`src/.env.example` → `src/.env` (aplicação) e `PostDocker/.env.example` → `PostDocker/.env`
(contêineres). As
variáveis `POSTGRES_*` precisam bater com `DB_USER`, `DB_PASSWORD` e `DB_NAME` do `src/.env`,
senão a aplicação não conecta no banco que o contêiner criou.

```bash
# 1. Infraestrutura (o docker-compose.yml fica em PostDocker/, não na raiz)
cd PostDocker && docker compose up -d && cd ..

# 2. API
source .venv/bin/activate
uvicorn src.api.main_api:app --reload --host 0.0.0.0

# 3. Bot do Discord (outro terminal)
source .venv/bin/activate
python -m src.bot.bot
```

**O bot precisa ser executado como módulo (`-m`).** `python src/bot/bot.py` falha com
`ModuleNotFoundError: No module named 'src'`, porque o Python coloca `src/bot/` no path
em vez da raiz. Vale para qualquer script do projeto.

**O bot não tem reload.** Mexeu em `raffle_service.py` ou `raffle_commands.py`, para e sobe de novo.

**Python 3.13.** No 3.14 as versões fixadas no `requirements.txt` não têm wheel e o
`psycopg2-binary` tenta compilar, falhando por falta do `pg_config`.

O `README.md` tem a instalação completa a partir do clone — cadastro dos apps do Discord e da
Twitch, conta separada do bot, ngrok, os dois `.env` e a ordem das autenticações. Consulte-o
antes de supor como algo é configurado.

## Arquitetura

- **`src/bot/`** — bot do Discord (`discord.py`). Comandos e o laço do sorteio.
- **`src/api/`** — backend FastAPI. Callbacks de OAuth, webhook de chat da Twitch, envio de mensagens.
- **`src/database/`** — repositórios de PostgreSQL (psycopg2 + connection pool próprio) e Redis.
- **`src/core/config.py`** — toda a configuração, lida do `.env`.

Comandos do Discord: `/registrar_itens`, `/iniciar_sorteio`, `/parar`,
`/autenticar_plataformas` (slash) e `!autenticar` (prefixo, para o viewer).

O `!autenticar` é o único comando por prefixo e **depende do intent privilegiado
Message Content**, habilitado no Developer Portal do Discord. Se ele for desligado, o
comando para de funcionar em silêncio — sem erro e sem log. Os comandos slash não têm
essa dependência.

O `/registrar_itens` usa um **Modal** do discord.py (formulário na interface) em vez de
argumentos. É o padrão a seguir para qualquer comando novo que peça vários campos.

## Os três tokens da Twitch

Confundir os três é a maior fonte de erro neste projeto.

| Token | Onde fica | Como se obtém | Para quê |
|---|---|---|---|
| **Streamer** | `streamer_platform`, `platform_name='twitch'` | `/autenticar_plataformas` → embed da Twitch | Consentimento `channel:bot` no canal |
| **Bot** | `streamer_platform`, `platform_name='twitch_bot'` | `/autenticar_plataformas` → embed do Bot, **logado na conta do bot** | Envia as mensagens no chat |
| **App Access Token** | `app_access_token` | `client_credentials`, gerado sozinho quando falta ou vence | Cria as inscrições de EventSub |

A conta do bot na Twitch é **separada** da conta do streamer; seu id está em
`config.twitch['BOT_PLATFORM_ID']`. Os dois primeiros são tokens de usuário: só existem
depois de alguém autorizar no navegador, não há como gerá-los programaticamente.
O terceiro é totalmente automático (`AuthService.get_app_access_token`).

**Os tokens são gravados cifrados** (Fernet, `src/core/criptografia.py`), com a chave
`TOKEN_ENCRYPTION_KEY` do `src/.env`. A cifragem fica toda em `PostgresRepositoryAuth`: quem
chama continua entregando e recebendo o dicionário do token. No banco fica o envelope
`{"alg": "fernet", "kid": 1, "ct": ...}`. Um token sem envelope (texto puro) é **recusado**
na leitura com `TokenSemCriptografiaError`, nunca usado; o App Access Token, por ser
automático, é regerado nesse caso. O `expires_at` continua em coluna própria e em claro.

## Como o `!claim` funciona

1. O sorteio escolhe um viewer aleatório de `authenticated_users` (**não** consulta a lista
   de chatters da Twitch — esse fluxo foi aposentado e o `get_chatters` está comentado).
2. Apaga a chave de claim desse viewer no Redis e anuncia no chat da Twitch.
3. O viewer digita `!claim`. A Twitch chama o webhook `/twitch/eventsub` (EventSub,
   `channel.chat.message`), validado por HMAC-SHA256.
4. O webhook grava no Redis: **`claim:twitch:{broadcaster_id}:{chatter_id}`**
5. O sorteio consulta essa chave.

**As duas pontas precisam montar a chave igual.** Já houve um bug em que o webhook usava o
id do canal e o sorteio usava o id do viewer — coincidia só quando o viewer era o dono do
canal. Os dois ids são necessários: pode haver mais de uma live simultânea com o mesmo viewer.

Mensagens da própria conta do bot são descartadas na entrada do webhook.

O segredo do HMAC vem de `TWITCH_WEBHOOK_SECRET` no `src/.env`. A Twitch assina com o segredo
dado na **criação** da inscrição e não deixa trocá-lo depois; por isso a coluna
`webhook_secret` guarda a impressão digital do segredo (`sha256:...`) e, no 409, a inscrição
só é reaproveitada se a impressão digital bater, senão é apagada e recriada. Assinatura
inválida devolve 403.

## Banco de dados

O banco é o **`live_loot_bot_test`** (ver `DB_NAME` no `.env`). Os antigos `_dev` e `_prod`,
que carregavam um schema de uma versão anterior, foram removidos — existe apenas um agora.

**Quase tudo tem `ON DELETE CASCADE` para `streamer(id)`.** Apagar a linha do streamer leva
junto `streamer_platform` (os dois tokens), `authenticated_users` (todos os viewers),
`raffle_items` e `twitch_eventsub_subscription`. Só o `app_access_token` sobrevive.

A lógica ponderada do sorteio vive no banco, na função PL/pgSQL `make_raffle(guild_id)`.

O `docker compose up` monta `migrations/000_schema_inicial.sql` em
`/docker-entrypoint-initdb.d/`, então **um volume novo já nasce com o schema aplicado**.
Só acontece na primeira criação do volume; para refazer, `docker compose down -v`.

O schema está versionado em `migrations/` — ver o `README.md` de lá. O
`000_schema_inicial.sql` cria o banco inteiro do zero, incluindo as funções `insert_items` e
`make_raffle`. **As migrações não rodam sozinhas**, são aplicadas à mão (DBeaver ou `psql`).

## Armadilhas conhecidas

- **O `.env` fica em `src/`**, não na raiz. Funciona porque o `load_dotenv()` procura a partir
  da pasta do `config.py`, não do diretório atual. `source .env` da raiz falha.
- **Os arquivos são CRLF.** Ao editar programaticamente, preserve o line ending original,
  senão o diff incha e fica ilegível.
- **O ngrok roda em contêiner.** No Linux precisa de
  `extra_hosts: - "host.docker.internal:host-gateway"` no serviço, e o uvicorn tem que subir
  com `--host 0.0.0.0` — senão o túnel não alcança a API (`ERR_NGROK_8012`).
- **O firewall do sistema é a outra causa do `ERR_NGROK_8012`**, e a mais difícil de
  enxergar: `ufw` ou `firewalld` ativos descartam o tráfego vindo das redes do Docker, sem
  deixar log nenhum na API. A mensagem do ngrok distingue os casos — `connection refused` é
  API fora do ar, `no such host` é o `extra_hosts`, `connection timed out` é firewall. A
  liberação vai pela faixa `172.16.0.0/12`, não pela interface: o compose cria a rede
  `app-network`, que no host é uma `br-<id>` e não a `docker0`, e esse nome muda a cada
  `docker compose down`. Os comandos estão no `README.md`.
- **Os redirect URIs precisam estar cadastrados** no app da Twitch (`/streamer`, `/viewer`,
  `/bot`), senão o OAuth devolve `redirect_mismatch`.
- **Os arquivos `__init__` estão grafados `__inity__.py`.** Funciona por acaso (namespace
  packages), mas é um erro.
- `src/api/routes/teste.py` e `src/bot/services/test.py` são rascunhos; o primeiro dispara
  uma requisição HTTP ao ser importado.

## Como validar mudanças

Não há testes automatizados no repositório, mas **dá para validar de verdade sem depender do
ambiente do autor**: o contêiner tem PostgreSQL 16 (`/usr/lib/postgresql/16/bin`) e
`redis-server` disponíveis. O procedimento usado até aqui:

1. Subir um cluster temporário (`initdb` + `pg_ctl` numa porta alternativa) e um `redis-server`
2. Carregar o schema a partir de um dump do banco real
3. Popular com dados de exemplo e exercitar o código com as variáveis de ambiente apontando
   para essa instância
4. Para as rotas, subir a API real com `uvicorn` numa thread e bater nela com requisições —
   inclusive concorrentes, para medir bloqueio
5. Para o webhook, montar a assinatura HMAC de verdade em vez de contornar a validação

Foi assim que se mediu o ganho de concorrência (3,04s → 1,04s em três requisições simultâneas)
e que se reproduziu a queda de conexões do pool. Vale repetir esse padrão em vez de confiar
em inspeção de código.

## Scripts

`scripts/token_bot.py` monta a URL de autorização da conta do bot e troca o code pelo token,
imprimindo o INSERT pronto. **Está obsoleto** desde que a rota `/twitch_callback/bot` passou a
fazer isso pelo comando do Discord, e o INSERT que ele gera grava o token em texto puro, que
agora é recusado na leitura. Pode ser removido.

## Branches

- `master` — versão antiga
- `new_method` — base do trabalho atual
- `remove_kick` — remove a integração com a Kick (havia suporte a duas plataformas)
- `tokens_twitch` — a partir da anterior: App Access Token automático, rota
  `/twitch_callback/bot`, correção da chave do claim, tratamento do 409 do EventSub,
  verificação de conexão no pool, e trabalho bloqueante fora do laço de eventos

Nenhuma foi mesclada na `new_method` ainda.

## Concorrência

As rotas que usam `requests` e `psycopg2` (bloqueantes) são declaradas **síncronas** de
propósito: o FastAPI as executa num pool de threads. Declará-las `async` travaria o laço de
eventos e a API inteira pararia enquanto a Twitch responde.

**Exceção:** `twitch_eventsub` é `async` porque usa `await request.body()`.

No bot, o envio de mensagens vai por `asyncio.to_thread`, para não travar o heartbeat do
discord.py.

## Pendências conhecidas

- `RaffleService.raffle_viewer` devolve um valor quando falha e dois quando dá certo;
  `/iniciar_sorteio` estoura com `cannot unpack non-iterable NoneType` se não houver
  viewer autenticado.
- Intervalo entre rodadas, janela do claim e número de tentativas estão fixos no código;
  o TCC promete que o criador configura esses valores.
- As URLs de autorização do streamer e do viewer têm o endereço do ngrok fixo no
  `raffle_service.py`, embora já exista `URL_BASE` no `.env`.
