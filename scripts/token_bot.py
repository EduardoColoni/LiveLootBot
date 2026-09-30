"""
Ajuda a pegar o token da conta do BOT na Twitch, que hoje não tem rota no código.

Rode da RAIZ do projeto, com o venv ativo:

    python scripts/token_bot.py url <guild_id>
        Imprime a URL de autorização. Abra no navegador LOGADO NA CONTA DO BOT.
        Depois de autorizar você cai numa página de erro ("Apenas um streamer
        pode ser cadastrado") — isso é esperado. Copie o valor de code= da barra
        de endereços.

    python scripts/token_bot.py trocar <guild_id> <code>
        Troca o code pelo token e imprime o INSERT pronto para colar no DBeaver.
        O code expira em poucos minutos e só serve uma vez.
"""
import os
import sys
import uuid
import json
import base64
import urllib.parse

import requests

# Rodando como "python scripts/token_bot.py", o Python coloca scripts/ no path,
# e não a raiz do projeto — sem isso o "from src..." abaixo não encontra nada.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import twitch

# Precisa ser idêntico ao redirect_uri usado na URL de autorização
REDIRECT_URI = "https://remarkably-knowing-serval.ngrok-free.app/twitch_callback/streamer"

# Escopos da conta do bot (mesmos do twitch_auth_url_bot em raffle_service.py)
SCOPES = "chat:read+chat:edit+user:read:chat+user:write:chat+user:bot+moderator:read:chatters"

BOT_PLATFORM_ID = "1355737213"  # mesmo id hardcoded em twitch_chatters_routes.py


def montar_url(guild_id: str) -> str:
    state_dict = {"guild_id": guild_id, "csrf": str(uuid.uuid4())}
    state_json = json.dumps(state_dict)
    encoded_state = urllib.parse.quote_plus(base64.b64encode(state_json.encode()).decode())

    return (
        twitch["TWITCH_URL"] + "/authorize?"
        "response_type=code&"
        f"client_id={twitch['CLIENT_ID']}&"
        f"redirect_uri={urllib.parse.quote_plus(REDIRECT_URI)}&"
        f"scope={SCOPES}&"
        f"state={encoded_state}"
    )


def trocar_code(code: str) -> dict:
    response = requests.post(
        f"{twitch['TWITCH_URL']}/token",
        data={
            "client_id": twitch["CLIENT_ID"],
            "client_secret": twitch["CLIENT_SECRET"],
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=10,
    )
    if response.status_code != 200:
        print(f"\nA Twitch recusou a troca ({response.status_code}):\n{response.text}\n")
        print("Causas comuns: o code já foi usado, expirou, ou o redirect_uri não bate.")
        print("Se for isso, rode o 'url' de novo e refaça a autorização.")
        sys.exit(1)

    return response.json()


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    comando = sys.argv[1]
    guild_id = sys.argv[2]

    if comando == "url":
        print("\nAbra a URL abaixo no navegador LOGADO NA CONTA DO BOT:\n")
        print(montar_url(guild_id))
        print("\nDepois de autorizar, copie o code= da barra de endereços e rode:")
        print(f"    python scripts/token_bot.py trocar {guild_id} <o_code>\n")

    elif comando == "trocar":
        if len(sys.argv) < 4:
            print("Falta o code. Uso: python scripts/token_bot.py trocar <guild_id> <code>")
            sys.exit(1)

        token_json = trocar_code(sys.argv[3])
        print("\nToken recebido. Escopos:", token_json.get("scope"))

        token_sql = json.dumps(token_json).replace("'", "''")
        print("\nCole este INSERT no DBeaver (banco live_loot_bot_test):\n")
        print(
            "INSERT INTO streamer_platform (streamer_id, platform_id, platform_name, token)\n"
            "VALUES (\n"
            f"    (SELECT id FROM streamer WHERE guild_id = '{guild_id}'),\n"
            f"    '{BOT_PLATFORM_ID}',\n"
            "    'twitch_bot',\n"
            f"    '{token_sql}'::jsonb\n"
            ")\n"
            "ON CONFLICT (platform_id) DO UPDATE\n"
            "    SET token = EXCLUDED.token, updated_at = NOW();\n"
        )

    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
