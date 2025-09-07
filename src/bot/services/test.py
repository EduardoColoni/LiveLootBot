from src.database.postgres.connection.postgres_connection import PostgresPool
from src.database.postgres.postgres_repository_raffle import PostgresRepositoryRaffle
import requests
from src.core.config import api_config
url_base = api_config["URL_BASE"]

def teste():
    PostgresPool.init_pool(minconn=1, maxconn=5)
    conn = PostgresPool.get_conn()
    repo_auth = PostgresRepositoryRaffle(conn)
    #
    # response = repo_auth.select_streamer_platforms(64)
    # params = {
    #     "platform_id": "138603338",
    #     "user_id": "juninho",
    #     "item_name": "batata_doce"
    # }

    headers = {
        "Authorization": f"Bearer jzbwfvnbea5yiomknl4yeknn2jrck0",
        "Client-Id": 'qamgu47p8wl6qio8fa2ef3e37q3eu2'
    }
    platform_id = '138603338'
    user_id = 'teste'
    item_name = 'teste'
    json_body = {
        "broadcaster_id": platform_id,
        "moderator_id": "1355737213",
        "sender_id": "1355737213",
        "message": f"Parabéns @{user_id} você foi sorteado! e ganhou o item: {item_name}"
    }

    response_test = requests.post(
                "https://api.twitch.tv/helix/chat/messages",
                headers=headers,
                json=json_body
            )

    params = {
        "platform_id" : "138603338"
    }

    # response = requests.get(f"{url_base}/twitch_callback/get_refreshToken", params=params)


    # teste_viewer = repo_auth.raffle_viewer(64)
    # print(teste_viewer)
    #
    # if not teste_viewer:
    #     print("Nenhum viewer cadastrado")
    # else:
    #     print(f"{teste_viewer['discord']['user_name']}")
    # teste_doque_vem = repo_auth.select_streamer_platforms(60)
    # print(f"\n{teste_doque_vem}\n")
    #
    # print(f"\ntwitch{teste_doque_vem['twitch']['platform_id']}\n")
    # print(f"\nkick{teste_doque_vem['kick']['platform_id']}\n")
    #
    # print(f"\nkick{teste_doque_vem['kick']['platform_id']}\n")
    # print(f"\ntwitch{teste_doque_vem['twitch']['platform_id']}\n")
    print(response_test)
#
teste()
#
#
# @staticmethod
#     def raffle_viewer(platform_id: int):
#         url_base = api_config["URL_BASE"]
#
#         def get_chatters():
#             resp = requests.get(f"{url_base}/get_chatters/{platform_id}")
#             if resp.status_code != 200:
#                 raise RuntimeError(f"Erro ao buscar chatters: {resp.status_code} - {resp.text}")
#             try:
#                 return resp.json()
#             except ValueError as e:
#                 raise RuntimeError(f"Resposta não é JSON: {e}")
#
#         try:
#             raw_viewers = get_chatters()
#         except RuntimeError:
#             # Tentativa de refresh
#             refresh_resp = requests.get(f"{url_base}/get_refreshToken")
#             if refresh_resp.status_code != 200:
#                 raise RuntimeError(f"Falha ao renovar token: {refresh_resp.status_code} - {refresh_resp.text}")
#             # Tentativa novamente após refresh
#             raw_viewers = get_chatters()
#
#         viewers_list = raw_viewers.get("data", [])
#         if not viewers_list:
#             raise RuntimeError("Nenhum viewer retornado.")
#
#         return random.choice(viewers_list)