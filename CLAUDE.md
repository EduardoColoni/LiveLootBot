# LiveLootBot

Sistema de sorteios automáticos durante transmissões ao vivo, integrando Discord e Twitch.
Projeto de TCC. Código, comentários e mensagens de commit em português.

A monografia descreve, em vários pontos, uma arquitetura **anterior** à atual — em especial o
fluxo de escolha do ganhador, que consultava a lista de espectadores do chat da Twitch. **A
referência é sempre o código**, não o texto do TCC. As funcionalidades que o TCC promete e o
sistema ainda não tem estão na **Lista de tarefas**, no fim deste arquivo.

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
argumentos. É o padrão a seguir para qualquer comando novo que peça vários campos. O formato
é `item:peso, item:peso` (o `;` também é aceito como separador entre nome e peso), tratado em
`RaffleService.organizar_itens`.

O bot **não fala com a Twitch diretamente**: para mandar mensagem no chat, chama a rota
`POST /twitch_chatters/send_message` da API (`RaffleService.send_message_to_api`). O bot acessa
o PostgreSQL e o Redis diretamente.

A **inscrição de eventos do chat** (EventSub) não tem comando no Discord: é criada chamando
`GET /twitch_callback/event_sub_signature?platform_id=<id do canal>` à mão (curl), depois das
autenticações do streamer e do bot. Ver o "Primeiro uso" do `README.md`.

## Os três tokens da Twitch

Confundir os três é a maior fonte de erro neste projeto.

| Token | Onde fica | Como se obtém | Para quê |
|---|---|---|---|
| **Streamer** | `streamer_platform`, `platform_name='twitch'` | `/autenticar_plataformas` → embed da Twitch | Consentimento `channel:bot` no canal |
| **Bot** | `streamer_platform`, `platform_name='twitch_bot'` | `/autenticar_plataformas` → embed do Bot, **logado na conta do bot** | Envia as mensagens no chat |
| **App Access Token** | `app_access_token` | `client_credentials`, gerado sozinho quando falta ou vence | Cria as inscrições de EventSub |

O espectador (`!autenticar`, escopo `user:read:email`) **não gera token guardado**: só a
identidade (id e nome no Discord e na Twitch) vai para `authenticated_users`.

Escopos pedidos (montados em `RaffleService.streamer_auth_method` e `viewer_auth_method`):
streamer `channel:bot moderator:read:chatters`; bot `chat:read chat:edit user:read:chat
user:write:chat user:bot moderator:read:chatters`; viewer `user:read:email`. O
`moderator:read:chatters` e o `user:read:email` não são usados por nada hoje (ver tarefas).

Renovação: o App Access Token é regerado sozinho; o token do bot é renovado com o refresh
token quando a Twitch devolve 401 no envio (`twitch_chatters_routes.send_message`), e o envio é
repetido; o token do streamer só serve para o consentimento e não é usado depois.

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

## Ciclo do sorteio

O laço fica em `RaffleService.raffle_loop` e é disparado por `/iniciar_sorteio`
(`raffle_commands.py`). Os tempos estão **fixos no código** (ver tarefa A1):

1. Um sorteio por servidor (`cog.services[guild_id]`); `/parar` liga `user_input = False`, e o
   laço só confere isso no início da rodada seguinte — a rodada em andamento termina.
2. A cada rodada: espera o intervalo (`raffle_loop(10, ...)` → 10 s) e chama a função do banco
   `make_raffle(guild_id)`, que escolhe um item **ponderado pelo peso**, entre os itens sem
   ganhador do **cadastro mais recente** (`MAX(raffle_id)`). Sem item → o laço termina.
3. Sorteio binário: `random.choice([True, False])` decide se há prêmio na rodada.
4. Até **3 tentativas** por item (`make_raffle_bot`). Em cada uma: sorteia um viewer de
   `authenticated_users` (`ORDER BY RANDOM()`, pode repetir a pessoa — tarefa A3), apaga a
   chave de claim dele no Redis, manda a mensagem `claim` no chat, espera **10 s** e consulta o
   Redis. Sem claim: espera mais 5 s, manda `resend_claim` e tenta de novo.
5. Com claim: grava em `raffle_items.winner` o **nome do Discord** do ganhador, manda `winner`
   no chat da Twitch e anuncia no canal do Discord.
6. Três tentativas sem claim: manda `not-claim` no chat. O item continua sem ganhador e volta a
   concorrer nas rodadas seguintes.
7. Sem nenhum viewer autenticado: `raffle_viewer` levanta `SemEspectadoresError`, e o
   `/iniciar_sorteio` avisa no Discord e libera o servidor.

O `raffle_id` **não é a rodada do laço**: é o número de cada cadastro de itens. Cada
`/registrar_itens` gera o próximo (`MAX(raffle_id) + 1` do streamer, em
`PostgresRepositoryRaffle.make_raffle_id`); não é chave estrangeira.

Qualquer viewer autenticado no servidor pode ser sorteado, mesmo sem estar na live — o que
garante a presença é o `!claim` com prazo.

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

Mensagens da própria conta do bot são descartadas na entrada do webhook. O texto precisa ser
**exatamente** `!claim`. A chave expira em **17 s** (`insert_ex` em `twitch_event_sub.py`).
Todo `!claim` é gravado, mas o sorteio só consulta a chave do viewer sorteado.

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
Conferida em 6.000 sorteios com pesos 10/30/60: 10,2% / 29,7% / 60,1%.

**Regras impostas pelo próprio banco** (restrições de unicidade, testadas):
`streamer.guild_id` único (um streamer por servidor); `streamer_platform.platform_id` único (um
canal da Twitch não entra num segundo servidor — o insert falha); `authenticated_users` único
por `(streamer_id, discord_id)` (o mesmo viewer participa de servidores diferentes; uma nova
autorização no mesmo servidor atualiza a linha).

**O `DEFAULT 50` de `raffle_items.weight` não tem efeito hoje:** `insert_items` sempre envia o
peso, inclusive `NULL`, e o default só vale quando a coluna é omitida. Item com peso `NULL` (ou
0) nunca é sorteado — ver tarefa A2.

A coluna `twitch_eventsub_subscription.webhook_secret` guarda a **impressão digital** do segredo,
não o segredo; `token`/`token_data` guardam o envelope cifrado.

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
  `/bot`), senão o OAuth devolve `redirect_mismatch`. Os links que o bot manda no Discord e
  as trocas de code nos callbacks usam os três `REDIRECT_URI_*` do `.env`; nenhum endereço
  fica no código.

## Como validar mudanças

Há uma suíte em `tests/` (pytest) que roda contra **PostgreSQL e Redis de verdade**, sem
simular o banco. Só a Twitch é simulada (`TwitchFalsa`, no `conftest.py`); a API sobe com
`uvicorn` numa thread e as requisições são HTTP de verdade, com assinatura HMAC real no
webhook.

```bash
pip install -r requirements-dev.txt
python -m pytest -v
```

Não encosta nos dados reais: usa o banco `live_loot_bot_pytest` (recriado do zero a cada
execução a partir do `000_schema_inicial.sql`) e o banco 15 do Redis, com chave de
criptografia e segredo de webhook próprios. As credenciais vêm do `src/.env`; os nomes podem
ser trocados com `TEST_DB_NAME` e `TEST_REDIS_DB`.

Cobre: criptografia dos tokens, webhook (HMAC, 403, claim, mensagem do bot), simetria da
chave do claim entre webhook e sorteio, os casos do 409 do EventSub, callbacks de OAuth do
streamer e do bot, `redirect_uri` dos links de autorização igual ao da troca do code, renovação do token no envio de mensagem, pool sob queda de conexões e
concorrência (três envios de 1s terminam em ~1s, não em 3s) e o laço do sorteio, rodando
o `/iniciar_sorteio` de verdade com uma interação do Discord simulada (`test_sorteio.py`).
**Não cobre** a conexão com o Discord em si nem os demais comandos do bot.

Fora da máquina do autor, o contêiner tem PostgreSQL 16 (`/usr/lib/postgresql/16/bin`) e
`redis-server`: basta subir um cluster temporário (`initdb` + `pg_ctl` numa porta
alternativa) e um `redis-server`, e apontar `DB_HOST`/`DB_PORT`/`REDIS_PORT` para eles. A
pasta de dados do `initdb` precisa ficar num lugar acessível ao usuário `postgres` (por
exemplo, `/var/tmp`). Teste novo segue o mesmo princípio: nada de simular o banco.

## Branches

O **`master`** é a branch principal e tem todo o trabalho atual. Trabalho novo sai de uma
branch a partir do `master`, a não ser que o usuário peça para fazer direto no `master` (já
aconteceu com correções pequenas). Já recebeu, em ordem:

- `new_method` — base do trabalho atual
- `remove_kick` — remove a integração com a Kick (havia suporte a duas plataformas)
- `tokens_twitch` — App Access Token automático, rota `/twitch_callback/bot`, correção da
  chave do claim, tratamento do 409 do EventSub, verificação de conexão no pool, trabalho
  bloqueante fora do laço de eventos
- `criptografia_tokens` — tokens cifrados (Fernet), segredo do webhook no `.env`, suíte de
  testes em `tests/`, remoção de rascunhos e do `scripts/token_bot.py`, `__init__.py`
  corrigidos, endereços do ngrok fora do código e logs sem dados pessoais

`new_method` e `kick` continuam no remoto só como histórico.

Depois disso, direto no `master`: o `/iniciar_sorteio` deixou de quebrar sem viewer
autenticado (`SemEspectadoresError`), com o teste `tests/test_sorteio.py`.

## Logs

Os `print` usam prefixos por área: `[OAuth]`, `[EventSub]`, `[Chat]`, `[Sorteio]`. **Nunca
imprimir** token, resposta bruta da Twitch, objeto de usuário ou de evento inteiro, nem nome
ou e-mail: já houve `print` de depuração mostrando o perfil completo do viewer, com e-mail.
Ids de inscrição e o tipo da mensagem (`claim`, `winner`...) são suficientes para acompanhar.

## Concorrência

As rotas que usam `requests` e `psycopg2` (bloqueantes) são declaradas **síncronas** de
propósito: o FastAPI as executa num pool de threads. Declará-las `async` travaria o laço de
eventos e a API inteira pararia enquanto a Twitch responde.

**Exceção:** `twitch_eventsub` é `async` porque usa `await request.body()`.

No bot, o envio de mensagens vai por `asyncio.to_thread`, para não travar o heartbeat do
discord.py.

## Lista de tarefas da aplicação

Abertas, em ordem de prioridade para a apresentação. **Ao concluir uma, tire daqui** e registre
o que mudou na seção correspondente acima.

As três primeiras são funcionalidades que o TCC descreve e que **vão ser implementadas** (o
texto do TCC fica como está; quem muda é o sistema):

- **A1. Tempos configuráveis pelo criador.** Intervalo entre rodadas (hoje `raffle_loop(10, ...)`
  em `raffle_commands.py`) e prazo do `!claim` (hoje `asyncio.sleep(10)` + `sleep(5)` em
  `make_raffle_bot` e TTL de 17 s em `twitch_event_sub.py`). O número de tentativas (3) já
  bate com o TCC.
- **A2. Pesos: padrão 50 e limite de 1 a 100.** Hoje, em `organizar_itens`: item sem `:` faz o
  cadastro inteiro falhar ("verifique a formatação"); peso não numérico vira `NULL` e o item
  nunca sai; peso 0 é aceito e nunca sai; acima de 100 é aceito.
- **A3. Nova tentativa sempre com outro viewer.** Hoje cada tentativa sorteia entre todos e pode
  repetir a pessoa. Definir o que fazer quando houver menos viewers que tentativas.

Falhas encontradas no sistema:

- **A4. Prazo anunciado no chat.** A mensagem `claim` diz "Digite !claim em até 1 minuto"
  (`message_map` em `twitch_chatters_routes.py`), mas a espera real é ~10 s. Resolver junto com
  o A1, mostrando o prazo configurado.
- **A5. Aviso errado no Discord.** Depois de 3 tentativas sem claim, `raffle_loop` chama
  `on_winner_callback(None)`, e o Discord recebe "Itens para sorteio vazio ou usuário parou a
  função" — embora o sorteio continue.
- **A6. Escopos que sobraram.** Tirar `user:read:email` (viewer) e `moderator:read:chatters`
  (streamer e bot), que só serviam ao fluxo antigo dos chatters.
- **A8. Canal repetido em outro servidor.** O banco recusa (correto), mas o callback do streamer
  só trata `ValueError` e `RequestException`: o `RuntimeError` do repositório vira "Internal
  Server Error" para o usuário.
- **Log de acesso do uvicorn** mostra a query string inteira: nos callbacks de OAuth, o `state`
  (base64 com id e nome do Discord do viewer) e o `code` (uso único); no
  `/twitch_chatters/send_message`, o nome do ganhador em `user_name`.
- **`status_map` do EventSub** (`event_sub_signature`) mapeia `expired`, mas o enum
  `eventsub_status` do banco só tem `enabled`, `pending` e `disabled`.
