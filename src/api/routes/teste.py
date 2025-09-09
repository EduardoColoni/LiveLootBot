import requests
from src.core.config import api_config
from src.database.postgres.postgres_repository_auth import PostgresRepositoryAuth
from src.database.postgres.connection.postgres_connection import PostgresPool

# Inicializa o pool (mesmo jeito que no main_api)
# PostgresPool.init_pool(minconn=1, maxconn=5)
# conn = PostgresPool.get_conn()
#
# streamer = "102089057"
# repo = PostgresRepositoryAuth(conn)
# teste = repo.select_token_by_streamer(streamer)
# print(teste['access_token'])
#
# PostgresPool.release_conn(conn)
# PostgresPool.close_all()



# response = requests.get(f"{url_base}/get_chatters/{46736025}")
url_base = api_config["URL_BASE"]
# response = requests.post(f"{url_base}/send_message/{138603338}/kinoyu_")
params_message = {
            "platform_id": "68332388",
            "user_name": "KinoYu",
            "item_name": "teste",
            "message_control" : "claim"
        }

response = requests.post(f"{url_base}/kick_chatters/send_message", params=params_message)


# import json
# import requests
#
# headers = {
#     "Authorization": "Bearer ZDA5NZU2ZTYTMJEWYS0ZNMVKLWI0NTCTMZU0OWNHZDEWMJY2",
#     "Content-Type": "application/json"
# }
#
# payload = {
#     "content": "teste123",
#     "reply_to_message_id": "",
#     "type": "bot"
# }
#
# response = requests.post(
#     "https://api.kick.com/public/v1/chat",
#     headers=headers,
#     data=json.dumps(payload)  # 👈 usa data + json.dumps como no exemplo oficial
# )

print(response.status_code)
print(response.text)


