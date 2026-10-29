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
`RaffleService.organizar_itens`: sem peso (`Teclado` ou `Teclado:`), o item vale **50**
(`PESO_PADRAO`); peso informado precisa ser inteiro de **1 a 100** (`PESO_MINIMO`,
`PESO_MAXIMO`). Se algum item tiver peso fora disso, ou se não houver item nenhum, o cadastro
inteiro é recusado com `ItensInvalidosError`, cuja mensagem lista os itens errados e vai para
o Discord — nada é gravado. O texto é conferido antes de abrir conexão com o banco.

O bot **não fala com a Twitch diretamente**: para mandar mensagem no chat, chama a rota
`POST /twitch_chatters/send_message` da API (`RaffleService.send_message_to_api`). O bot acessa
o PostgreSQL e o Redis diretamente.

A **inscrição de eventos do chat** (EventSub) é criada sozinha no fim da autenticação do bot
(`twitch_callback_bot` chama `TwitchAuthController.inscrever_chat` com o canal do streamer
daquele servidor). Se ela falhar, o token do bot continua gravado e a página diz que o chat
não foi conectado, com o motivo; autenticar o bot de novo tenta outra vez. A rota
`GET /twitch_callback/event_sub_signature?platform_id=<id do canal>` continua existindo para
refazer só a inscrição à mão, e usa a mesma função.

As **telas que a pessoa vê no navegador** ao fim de cada autorização (callbacks do streamer, do
bot e do viewer) saem todas do template `src/api/templates/pagina.html`, montado por
`pagina(request, tipo, titulo, *mensagens, detalhe=..., status_code=...)` em
`src/api/templating.py`, com o CSS em `src/api/static/css/paginas.css` e o logo em
`src/api/static/img/logo.png` (cores do avatar do bot: ciano neon sobre azul-marinho). O `tipo`
é `sucesso`, `aviso` ou `erro`. Sem Bootstrap nem CDN. O Jinja escapa todo o texto; para
destacar um trecho com HTML, use `Markup("... <strong>{}</strong>").format(valor)`, que escapa
o valor. Os casos repetidos nos três callbacks (sem `code`, link adulterado, Twitch recusou o
code, falha de conexão) são as funções `pagina_*` no topo de `twitch_auth_route.py`. Os
caminhos de CSS e logo são relativos (`/static/...`) de propósito: o `url_for` montaria
`http://` atrás do ngrok, e o navegador bloquearia numa página `https`.

## Os três tokens da Twitch

Confundir os três é a maior fonte de erro neste projeto.

| Token | Onde fica | Como se obtém | Para quê |
|---|---|---|---|
| **Streamer** | `streamer_platform`, `platform_name='twitch'` | `/autenticar_plataformas` → embed da Twitch | Consentimento `channel:bot` no canal |
| **Bot** | `streamer_platform`, `platform_name='twitch_bot'` | `/autenticar_plataformas` → embed do Bot, **logado na conta do bot** | Envia as mensagens no chat |
| **App Access Token** | `app_access_token` | `client_credentials`, gerado sozinho quando falta ou vence | Cria as inscrições de EventSub |

O espectador (`!autenticar`) **não gera token guardado**: só a identidade (id e nome no
Discord e na Twitch) vai para `authenticated_users`.

Escopos pedidos (montados em `RaffleService.streamer_auth_method` e `viewer_auth_method`):
streamer `channel:bot`; bot `chat:read chat:edit user:read:chat user:write:chat user:bot`;
viewer **nenhum** (`scope=` vazio), porque `/helix/users` devolve id e nome sem permissão. O
`moderator:read:chatters` (do fluxo antigo dos chatters) e o `user:read:email` foram retirados.

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
4. Até **3 tentativas** por item (`make_raffle_bot`). Em cada uma: escolhe um viewer (ver
   abaixo), apaga a chave de claim dele no Redis, manda a mensagem `claim` no chat, espera
   **10 s** e consulta o Redis. Sem claim: espera mais 5 s, manda `resend_claim` e tenta de novo.
5. Com claim: grava em `raffle_items.winner` o **nome do Discord** do ganhador, manda `winner`
   no chat da Twitch e anuncia no canal do Discord.
6. Três tentativas sem claim: manda `not-claim` no chat e avisa no Discord que o item volta a
   concorrer (`on_winner_callback(None, item)`; o `notify_winner` distingue esse caso do fim do
   sorteio, que é `on_winner_callback(None)`). O item continua sem ganhador.
7. Sem nenhum viewer autenticado: `raffle_viewer` levanta `SemEspectadoresError`, e o
   `/iniciar_sorteio` avisa no Discord e libera o servidor.

**Escolha do viewer** (`RaffleService.raffle_viewer`): a lista vem inteira do banco
(`select_viewers`, ordem de cadastro) e a escolha é em Python, por camadas de preferência —
nunca proibição, para o sorteio não travar em live com pouca gente:

1. alguém ainda não chamado **neste item** e que não ganhou o **último item**;
2. senão, alguém ainda não chamado neste item (o último ganhador é liberado primeiro);
3. senão, quem foi chamado há mais tempo neste item.

Resultado: com 3+ viewers, as 3 tentativas vão para 3 pessoas diferentes; com 2, A, B, A; com
1, A, A, A. Os chamados do item ficam na lista `chamados` do `raffle_loop`; o último ganhador
(discord id) fica em `self.ultimo_ganhador`, **só na memória do serviço**: um novo
`/iniciar_sorteio` começa sem bloqueio, e o bloqueio dura até haver outro ganhador (itens sem
ganhador no meio não o liberam). Nos testes, `random.choice` é trocado por "primeira opção"
para a escolha ser previsível.

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
só é reaproveitada se a impressão digital bater **e** o endereço dela for o `URL_BASE` atual;
senão (segredo trocado, banco apagado, domínio do ngrok trocado) é apagada e recriada.
Assinatura inválida devolve 403.

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
canal da Twitch não entra num segundo servidor — o callback do streamer confere antes e
responde 409 com mensagem clara; a restrição do banco fica como garantia); `authenticated_users` único
por `(streamer_id, discord_id)` (o mesmo viewer participa de servidores diferentes; uma nova
autorização no mesmo servidor atualiza a linha).

**O `DEFAULT 50` de `raffle_items.weight` não é usado:** `insert_items` sempre envia o peso, e
o default do banco só vale quando a coluna é omitida. Quem aplica o 50 é o
`organizar_itens`, então pelo bot o peso nunca chega `NULL` nem fora de 1 a 100. O banco em si
não tem `CHECK` de faixa: um item com peso `NULL` ou 0 inserido por fora (DBeaver) nunca seria
sorteado.

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
chave do claim entre webhook e sorteio, os casos do 409 do EventSub, a inscrição automática
ao autenticar o bot (inclusive com falha na Twitch), callbacks de OAuth do streamer e do bot, as páginas de cada desfecho dos callbacks (completas,
com CSS e logo servidos e texto de fora escapado, em `test_paginas.py`), `redirect_uri` dos links de autorização igual ao da troca do code, renovação do token no envio de mensagem, pool sob queda de conexões e
concorrência (três envios de 1s terminam em ~1s, não em 3s) e o laço do sorteio, rodando
o `/iniciar_sorteio` de verdade com uma interação do Discord simulada (`test_sorteio.py`), e o
cadastro de itens pelo formulário real do `/registrar_itens`, com os limites de peso e o
sorteio do item pela `make_raffle` (`test_itens.py`).
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
autenticado (`SemEspectadoresError`), com o teste `tests/test_sorteio.py`; e saíram as tarefas
A5 (aviso do Discord após 3 tentativas), A6 (escopos), A8 (canal repetido em outro servidor),
o filtro do log de acesso e o `expired` do `status_map` do EventSub.

Em seguida, por PR:

- `sorteio_sem_repeticao` — tarefa A3: viewer não se repete nas tentativas de um item e o
  último ganhador fica fora do item seguinte (preferências em camadas, em memória).
- `pesos_itens` — tarefa A2: peso padrão 50 e pesos só de 1 a 100 no `/registrar_itens`, com
  os testes em `tests/test_itens.py`.
- `inscricao_chat_automatica`: a inscrição de chat é criada no fim da autenticação do bot,
  sem o curl; inscrição com endereço antigo passa a ser recriada em vez de dar erro.
- `telas_estilizadas`: páginas dos callbacks de OAuth com o visual do bot (template único,
  CSS próprio), e o callback do streamer deixa de responder `null` quando a Twitch recusa o code.

**Branch parada de propósito: `rotas_manuais_locais`.** Tem a correção do primeiro item de
"Limitações conhecidas" (rotas de manutenção só em `localhost`, com testes), mas o autor
decidiu deixá-la **intocada** até a entrega do TCC: **não mesclar, não usar como base de
branch nova, não atualizar**. Serve só de referência de como resolver; trabalho novo sai
sempre do `master`. O `CLAUDE.md` de dentro dela descreve a correção como se existisse, o que
não vale para o `master`.

## Logs

Os `print` usam prefixos por área: `[OAuth]`, `[EventSub]`, `[Chat]`, `[Sorteio]`. **Nunca
imprimir** token, resposta bruta da Twitch, objeto de usuário ou de evento inteiro, nem nome
ou e-mail: já houve `print` de depuração mostrando o perfil completo do viewer, com e-mail.
Ids de inscrição e o tipo da mensagem (`claim`, `winner`...) são suficientes para acompanhar.

O **log de acesso do uvicorn** passa pelo filtro `SemQueryString` (`main_api.py`), que tira a
query string da linha de cada requisição: ela levaria o `state` dos callbacks de OAuth (id e
nome do Discord do viewer em base64) e o nome do ganhador no `send_message`. O filtro é
registrado ao importar a aplicação, então vale também com `--reload`.

## Concorrência

As rotas que usam `requests` e `psycopg2` (bloqueantes) são declaradas **síncronas** de
propósito: o FastAPI as executa num pool de threads. Declará-las `async` travaria o laço de
eventos e a API inteira pararia enquanto a Twitch responde.

**Exceção:** `twitch_eventsub` é `async` porque usa `await request.body()`.

No bot, o envio de mensagens vai por `asyncio.to_thread`, para não travar o heartbeat do
discord.py.

## Limitações conhecidas (fora do escopo da entrega)

Problemas já analisados que o autor decidiu **não resolver agora**: o foco é a entrega do
TCC. **Não corrigir sem o autor pedir**, nem "de passagem" em outra tarefa. Podem entrar na
monografia como limitações e trabalhos futuros.

- **Rotas de manutenção abertas pelo ngrok.** `/twitch_callback/twitch_app_access_token` e
  `/twitch_callback/event_sub_signature` atendem qualquer um na internet. A primeira gera um
  App Access Token novo e **o devolve na resposta**; a segunda cria, apaga e recria a
  inscrição do chat. O token só dá acesso às inscrições de EventSub do app e a dados
  públicos, não às contas do streamer nem do bot. Correção pronta na branch parada
  `rotas_manuais_locais` (ver "Branches"): só `127.0.0.1`/`::1` sem `X-Forwarded-For`, e a
  rota do token sem devolver o token.
- **`POST /twitch_chatters/send_message` aberta pelo ngrok.** Qualquer um pode fazer o bot
  mandar no chat as mensagens do sorteio (`claim`, `winner`...) com o nome e o item que
  quiser. Não dá para fechar como as rotas acima porque o bot do Discord a chama pelo
  `URL_BASE` (ngrok), em `RaffleService.send_message_to_api`. Correção sugerida: o bot chamar a
  API por `localhost` e a rota só atender local, ou uma chave compartilhada no `.env`.
- **`state` dos links de autorização sem assinatura.** O `state` leva o `guild_id` e, no
  viewer, o id e o nome do Discord, em base64; o campo `csrf` nunca é conferido. Com um
  `state` montado à mão, uma pessoa cadastra a mesma conta da Twitch várias vezes com ids do
  Discord inventados (a unicidade é por `(streamer_id, discord_id)`), e cada linha conta como
  um participante: mais chances no sorteio. Correção sugerida: assinar o `state` com HMAC e um
  segredo do `.env` ao gerar o link, e conferir no callback.
- **Token do bot com vários servidores.** A conta do bot é uma só e a linha do token também
  (`streamer_platform.platform_id` é único). Ela fica ligada ao streamer do **primeiro**
  servidor que autenticou o bot; autenticar o bot em outro servidor só troca o token
  (`insert_bot_token`, `ON CONFLICT (platform_id)`). O envio funciona em todos os canais,
  porque o token é buscado pelo `BOT_PLATFORM_ID` e cada streamer dá o próprio consentimento
  `channel:bot`. Mas apagar o streamer do primeiro servidor leva o token junto (`ON DELETE
  CASCADE`), e o bot para de falar em **todos** os servidores até ser autenticado de novo.

## Lista de tarefas da aplicação

**Foco atual: refinar o sistema para a entrega do TCC.** Mudanças que não servem a isso
(segurança, refatorações, melhorias "de passagem") ficam para depois; ver "Limitações
conhecidas".

Abertas, em ordem de prioridade para a apresentação. **Ao concluir uma, tire daqui** e registre
o que mudou na seção correspondente acima.

A primeira é uma funcionalidade que o TCC descreve e que **vai ser implementada** (o texto do
TCC fica como está; quem muda é o sistema):

- **A1. Tempos configuráveis pelo criador.** Intervalo entre rodadas (hoje `raffle_loop(10, ...)`
  em `raffle_commands.py`) e prazo do `!claim` (hoje `asyncio.sleep(10)` + `sleep(5)` em
  `make_raffle_bot` e TTL de 17 s em `twitch_event_sub.py`). O número de tentativas (3) já
  bate com o TCC.

Outros pontos:

- **A4. Prazo anunciado no chat.** A mensagem `claim` diz "Digite !claim em até 1 minuto"
  (`message_map` em `twitch_chatters_routes.py`), mas a espera real é ~10 s. **A espera curta é
  proposital, para agilizar os testes do autor** — não "corrigir" sozinho. Resolver junto com
  o A1, mostrando o prazo configurado.
