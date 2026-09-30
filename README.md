# 🎁 LiveLootBot

Sistema de sorteios automáticos durante transmissões ao vivo, integrando **Discord** e **Twitch**.

O criador de conteúdo cadastra prêmios pelo Discord e inicia um ciclo de sorteios. Durante a
transmissão, o bot anuncia os vencedores no chat da Twitch, o espectador confirma com um
comando, e o resultado volta para o Discord. Só participa quem vinculou as duas contas — o
que garante que o prêmio vá para alguém que realmente está na comunidade.

Projeto de Trabalho de Conclusão de Curso.

---

## Como funciona

```
  Criador                                                    Espectador
     │                                                            │
     │ /registrar_itens                                           │
     │ /iniciar_sorteio                                           │
     ▼                                                            │
 ┌─────────┐   sorteia item ponderado    ┌──────────────┐         │
 │   Bot   │ ──────────────────────────► │  PostgreSQL  │         │
 │ Discord │   sorteia um vinculado      │  make_raffle │         │
 └────┬────┘                             └──────────────┘         │
      │                                                           │
      │ "@fulano, digite !claim"          ┌──────────┐            │
      └─────────────────────────────────► │  Twitch  │ ◄──────────┘
                                          │   chat   │   !claim
                                          └────┬─────┘
                                               │ webhook (EventSub)
                                               ▼
                                     ┌──────────────────┐
                                     │  API + Redis     │
                                     │  registra claim  │
                                     └──────────────────┘
```

1. O criador cadastra os itens com pesos (`item:peso`) e inicia o ciclo
2. A cada rodada, um sorteio decide se haverá prêmio; havendo, uma função no PostgreSQL
   escolhe o item de forma ponderada pelo peso
3. O vencedor é sorteado **entre os espectadores que vincularam Discord e Twitch**
4. O bot o menciona no chat da Twitch e abre uma janela para o resgate
5. O espectador digita `!claim`; a Twitch notifica a API por webhook, que registra no Redis
6. O sorteio confirma o resgate, grava o vencedor e anuncia no Discord

---

## Tecnologias

| Camada | Tecnologia |
|---|---|
| Bot | Python 3.13 · discord.py |
| API | FastAPI · Uvicorn |
| Banco | PostgreSQL 16 · psycopg2 com connection pool |
| Cache | Redis |
| Integração | Twitch Helix API · EventSub (webhook) · OAuth 2.0 |
| Infra | Docker Compose · ngrok |

---

## Pré-requisitos

**Software**

- Python **3.13** — no 3.14 as dependências fixadas não têm wheel pronta e a instalação falha
- Docker e Docker Compose
- Git

**Contas e cadastros** (todos gratuitos)

- Uma aplicação no [Discord Developer Portal](https://discord.com/developers/applications)
- Uma aplicação no [Twitch Developer Console](https://dev.twitch.tv/console/apps)
- **Duas contas na Twitch**: a sua (que será o canal) e uma separada para o bot
- Uma conta no [ngrok](https://dashboard.ngrok.com) com um domínio estático

---

## Instalação

### 1. Clonar e preparar o ambiente Python

```bash
git clone https://github.com/EduardoColoni/LiveLootBot.git
cd LiveLootBot

python3.13 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m ensurepip --upgrade
pip install -r requirements.txt
```

Confirme a versão antes de seguir:

```bash
python -V        # precisa ser 3.13.x
```

### 2. Criar a aplicação do Discord

1. Em [discord.com/developers/applications](https://discord.com/developers/applications),
   clique em **New Application** e dê um nome
2. No menu **Bot**, clique em **Reset Token** e guarde o valor — é o `DISCORD_TOKEN`
3. Ainda em **Bot**, desça até **Privileged Gateway Intents** e **ative o
   `MESSAGE CONTENT INTENT`**

   > Sem esse intent o comando `!autenticar` para de funcionar **em silêncio** — sem erro e
   > sem log. Os comandos de barra não dependem dele.

4. Em **OAuth2 → URL Generator**, marque os escopos `bot` e `applications.commands`, e as
   permissões *Send Messages* e *Embed Links*. Abra a URL gerada para convidar o bot ao seu
   servidor

### 3. Criar a aplicação da Twitch

1. Em [dev.twitch.tv/console/apps](https://dev.twitch.tv/console/apps), clique em
   **Register Your Application**
2. **Category**: `Chat Bot` · **Client Type**: `Confidential`
3. Em **OAuth Redirect URLs**, cadastre os **três** endereços abaixo, trocando pelo seu
   domínio do ngrok (passo 5):

   ```
   https://SEU-DOMINIO.ngrok-free.app/twitch_callback/streamer
   https://SEU-DOMINIO.ngrok-free.app/twitch_callback/viewer
   https://SEU-DOMINIO.ngrok-free.app/twitch_callback/bot
   ```

   > Precisam ser idênticos caractere a caractere, sem barra no final. Qualquer diferença
   > resulta em `redirect_mismatch` na hora de autorizar.

4. Guarde o **Client ID** e gere um **Client Secret** — são `CLIENT_ID` e `CLIENT_SECRET`

### 4. Criar a conta do bot na Twitch

O bot fala no chat com uma **conta própria**, separada da sua. Crie uma conta nova na Twitch
(ou use uma que já tenha) e descubra o ID numérico dela — é o `BOT_PLATFORM_ID`.

> O ID numérico não é o nome de usuário. Dá para obtê-lo por qualquer consulta à API da
> Twitch, ou por sites de terceiros que convertem nome em ID.

### 5. Configurar o ngrok

A Twitch precisa alcançar a API pela internet, tanto para os redirecionamentos do OAuth
quanto para entregar os eventos de chat. Em desenvolvimento isso é resolvido por um túnel.

1. Crie a conta e copie o **Authtoken** do painel — é o `NGROK_TOKEN`
2. Em **Domains**, reserve um domínio estático (o plano gratuito dá um)
3. Edite `PostDocker/ngrok.yml` e troque o `hostname` pelo seu domínio:

```yaml
tunnels:
  fastapi:
    proto: http
    addr: host.docker.internal:8000
    hostname: SEU-DOMINIO.ngrok-free.app
```

### 6. Criar os dois arquivos de configuração

São **dois `.env` separados**, em pastas diferentes. Ambos estão no `.gitignore`.

#### `src/.env` — a aplicação

Há um modelo pronto no repositório, com comentários explicando cada valor:

```bash
cp src/.env.example src/.env
```

```env
# Discord
DISCORD_TOKEN=o_token_do_passo_2

# Twitch
CLIENT_ID=o_client_id_do_passo_3
CLIENT_SECRET=o_client_secret_do_passo_3
TWITCH_URL=https://id.twitch.tv/oauth2
BOT_PLATFORM_ID=o_id_numerico_do_passo_4
REDIRECT_URI_STREAMER=https://SEU-DOMINIO.ngrok-free.app/twitch_callback/streamer
REDIRECT_URI_VIEWER=https://SEU-DOMINIO.ngrok-free.app/twitch_callback/viewer

# Banco de dados
DB_HOST=localhost
DB_PORT=5432
DB_USER=dev_user
DB_PASSWORD=escolha_uma_senha
DB_NAME=live_loot_bot_test

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# URL pública da API
URL_BASE=https://SEU-DOMINIO.ngrok-free.app
```

> `REDIRECT_URI_BOT` é opcional: se não for definida, é derivada automaticamente de
> `URL_BASE`. O mesmo vale para `BOT_PLATFORM_ID`, que tem um valor padrão no código.

#### `PostDocker/.env` — os contêineres

```bash
cd PostDocker
cp .env.example .env
```

```env
# Precisam ser IGUAIS a DB_USER, DB_PASSWORD e DB_NAME do src/.env
POSTGRES_USER=dev_user
POSTGRES_PASSWORD=a_mesma_senha
POSTGRES_DB=live_loot_bot_test

NGROK_TOKEN=o_token_do_passo_5
```

> O Docker Compose só substitui `${VARIÁVEL}` a partir do `.env` que fica **ao lado do
> `docker-compose.yml`** — por isso os dois arquivos. Se os valores não baterem, os
> contêineres sobem mas a aplicação não conecta no banco.

### 7. Subir a infraestrutura

```bash
cd PostDocker
docker compose up -d
docker compose ps
```

Os três serviços (`postgres`, `redis`, `ngrok`) devem aparecer como *running*.

O schema do banco é aplicado **automaticamente** na primeira criação do volume — o
`migrations/000_schema_inicial.sql` é montado no diretório de inicialização do PostgreSQL.
Confirme:

```bash
docker compose logs postgres | grep 000_schema_inicial
```

Deve aparecer `running /docker-entrypoint-initdb.d/000_schema_inicial.sql`. E para ver o
resultado:

```bash
docker exec -it postgres psql -U dev_user -d live_loot_bot_test -c "\dt"
```

Esperado: seis tabelas — `app_access_token`, `authenticated_users`, `raffle_items`,
`streamer`, `streamer_platform` e `twitch_eventsub_subscription`.

### 8. Rodar a aplicação

São dois processos, em terminais separados, a partir da **raiz do projeto**.

```bash
# Terminal 1 — API
source .venv/bin/activate
uvicorn src.api.main_api:app --reload --host 0.0.0.0
```

```bash
# Terminal 2 — Bot do Discord
source .venv/bin/activate
python -m src.bot.bot
```

> **O `--host 0.0.0.0` é obrigatório.** Sem ele o uvicorn escuta apenas em `127.0.0.1` e o
> contêiner do ngrok não alcança a API.
>
> **O bot roda como módulo (`-m`).** `python src/bot/bot.py` falha com
> `ModuleNotFoundError: No module named 'src'`.

---

## Primeiro uso

A ordem importa: cada etapa depende da anterior.

### 1. Autenticar o criador de conteúdo

No seu servidor do Discord:

```
/autenticar_plataformas
```

O bot responde com três blocos. Clique em **"Autenticação na Twitch"** e autorize **logado na
sua conta** (a do canal).

### 2. Autenticar a conta do bot

O mesmo comando, mas clicando em **"Autenticação do Bot"** — e desta vez **logado na Twitch
com a conta do bot**. O jeito mais simples é abrir o link numa janela anônima.

> Se você autorizar com a conta errada, o sistema recusa e avisa qual conta foi usada e qual
> era a esperada. Nada é gravado.

Confirme que os dois foram registrados:

```sql
SELECT platform_name, platform_id FROM streamer_platform;
```

Devem aparecer `twitch` e `twitch_bot`.

### 3. Criar a inscrição de eventos do chat

```bash
curl "http://localhost:8000/twitch_callback/event_sub_signature?platform_id=SEU_ID_NA_TWITCH"
```

A resposta `null` significa **sucesso** (o endpoint não retorna conteúdo). No log da API você
verá o App Access Token sendo gerado sozinho e, em seguida, o desafio de verificação chegando
da Twitch.

```sql
SELECT subscription_id, status FROM twitch_eventsub_subscription;
```

### 4. Autenticar os espectadores

Cada espectador, no Discord:

```
!autenticar
```

E autoriza na Twitch. **Só quem fizer isso participa dos sorteios.**

### 5. Sortear

```
/registrar_itens      → ex: skin dourada:80, skin prata:20
/iniciar_sorteio
```

O peso define a chance relativa de cada item. Sem peso informado, o padrão é 50.

---

## Comandos

| Comando | Quem usa | O que faz |
|---|---|---|
| `/autenticar_plataformas` | criador | Links de autorização do criador e do bot |
| `!autenticar` | espectador | Vincula a conta da Twitch ao Discord |
| `/registrar_itens` | criador | Cadastra prêmios no formato `item:peso` |
| `/iniciar_sorteio` | criador | Inicia o ciclo (um por servidor) |
| `/parar` | criador | Interrompe o ciclo em execução |

---

## Estrutura do projeto

```
LiveLootBot/
├── src/
│   ├── api/                    # Backend FastAPI
│   │   ├── main_api.py         # Aplicação e registro das rotas
│   │   ├── routes/             # Callbacks de OAuth, envio de mensagens, overlay
│   │   ├── services/           # Webhook do EventSub e serviço de autenticação
│   │   └── templates/          # Overlay para OBS
│   ├── bot/                    # Bot do Discord
│   │   ├── bot.py              # Ponto de entrada
│   │   ├── commands/           # Comandos de barra e de prefixo
│   │   └── services/           # Laço do sorteio e regras
│   ├── core/config.py          # Configuração lida do .env
│   └── database/               # Repositórios de PostgreSQL e Redis
├── migrations/                 # Schema versionado (ver README de lá)
├── PostDocker/                 # Docker Compose e configuração do ngrok
├── scripts/                    # Utilitários de operação
└── requirements.txt
```

### Endpoints da API

| Rota | Para quê |
|---|---|
| `GET /twitch_callback/streamer` | Callback do OAuth do criador |
| `GET /twitch_callback/viewer` | Callback do OAuth do espectador |
| `GET /twitch_callback/bot` | Callback do OAuth da conta do bot |
| `GET /twitch_callback/twitch_app_access_token` | Gera um App Access Token manualmente |
| `GET /twitch_callback/event_sub_signature` | Cria a inscrição de eventos do chat |
| `POST /twitch/eventsub` | Recebe as mensagens do chat da Twitch |
| `POST /twitch_chatters/send_message` | Envia mensagem no chat |
| `GET /overlays/winner/{nome}` | Overlay do vencedor para o OBS |

---

## Banco de dados

Seis tabelas, todas ligadas a `streamer` com `ON DELETE CASCADE`:

| Tabela | Conteúdo |
|---|---|
| `streamer` | Criador de conteúdo, um por servidor do Discord |
| `streamer_platform` | Tokens do criador e da conta do bot |
| `authenticated_users` | Espectadores com Discord e Twitch vinculados |
| `raffle_items` | Prêmios cadastrados, com peso e vencedor |
| `twitch_eventsub_subscription` | Inscrições de eventos do chat |
| `app_access_token` | Token da aplicação, renovado automaticamente |

> **Cuidado com o cascade:** apagar a linha do `streamer` remove junto os dois tokens, todos
> os espectadores vinculados, os itens e as inscrições.

A lógica ponderada do sorteio é uma função PL/pgSQL (`make_raffle`), executada dentro do
banco. O schema completo, incluindo as funções, está em `migrations/` — veja o
[README de lá](migrations/README.md).

---

## Solução de problemas

**`ERR_NGROK_8012` ao abrir a URL pública**
O túnel não alcança a API. Verifique se o uvicorn subiu com `--host 0.0.0.0` e se o serviço
`ngrok` do compose tem a entrada `extra_hosts` (necessária no Docker do Linux).

**`redirect_mismatch` ao autorizar na Twitch**
A URL de redirecionamento não está cadastrada no app da Twitch, ou está diferente. Confira os
três endereços do passo 3 — sem barra no final, idênticos caractere a caractere.

**`Token do bot não está no banco` (HTTP 503) ao enviar mensagem**
Falta a etapa 2 do primeiro uso. Rode `/autenticar_plataformas` e clique em
*"Autenticação do Bot"*, logado com a conta do bot.

**`subscription already exists` (HTTP 409) ao criar a inscrição**
A inscrição existe na Twitch mas não no banco — acontece ao recriar o banco. O sistema trata
isso sozinho: ele localiza a inscrição existente e a registra. Se a mensagem disser que o
*callback* é diferente, apague a inscrição antiga pela API da Twitch e rode de novo.

**`ModuleNotFoundError: No module named 'src'`**
O comando foi executado de dentro de uma subpasta, ou pelo caminho do arquivo. Rode da raiz
do projeto e use `python -m src.bot.bot`.

**`!autenticar` não responde**
O intent **Message Content** está desativado no Discord Developer Portal. Os comandos de
barra continuam funcionando nesse caso, o que torna o sintoma confuso.

**A instalação das dependências falha compilando `psycopg2`**
O ambiente virtual foi criado com Python 3.14. Recrie com o 3.13.

**Recomeçar do zero**

```bash
cd PostDocker
docker compose down -v      # apaga os volumes — o banco inteiro vai junto
docker compose up -d
```

Depois é preciso refazer todas as autenticações do *Primeiro uso*.

---

## Autor

**Eduardo Coloni** — desenvolvimento backend, integrações e automação.
