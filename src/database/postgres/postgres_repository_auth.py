import json

import psycopg2
from psycopg2 import errorcodes

class PostgresRepositoryAuth:
    def __init__(self, conn):
        self.conn = conn  # Usa a conexão recebida

    def insert_user(
            self,
            streamer_id: int,
            discord_id: str,
            twitch_id: str = None,
            discord_user_name: str = None,
            twitch_user_name: str = None
    ):
        # Coloca todos os campos em um dicionário
        # Para uma plataforma nova, basta adicionar os campos dela aqui, no INSERT e nos values
        fields = {
            "twitch_id": twitch_id,
            "discord_user_name": discord_user_name,
            "twitch_user_name": twitch_user_name
        }

        # Monta o SET do ON CONFLICT dinamicamente, ignorando campos que são None
        set_clauses = ", ".join(
            f"{field} = COALESCE(EXCLUDED.{field}, authenticated_users.{field})"
            for field, value in fields.items()
        )

        query = f"""
        INSERT INTO authenticated_users
        (streamer_id, discord_id, twitch_id, discord_user_name, twitch_user_name, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT (streamer_id, discord_id) DO UPDATE
        SET {set_clauses},
            updated_at = NOW()
        """

        values = (streamer_id, discord_id, twitch_id, discord_user_name, twitch_user_name)

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, values)
            self.conn.commit()
        except psycopg2.Error as e:
            self.conn.rollback()
            raise RuntimeError(f"Failed to insert/update user: {e}")

    def new_insert_token(self, token_data: dict, guild_id: str, streamer_name: str, platform_id: str, platform_name: str):
        try:
            with self.conn.cursor() as cur:
                # 1. Tenta inserir o streamer. Se já existir, atualiza o nome e retorna o ID.
                cur.execute(
                    "INSERT INTO streamer (streamer_name, guild_id) VALUES (%s, %s) "
                    "ON CONFLICT (guild_id) DO UPDATE SET streamer_name = EXCLUDED.streamer_name RETURNING id",
                    (streamer_name, guild_id)
                )
                # A cláusula RETURNING id retorna o ID do registro inserido ou atualizado.
                streamer_id = cur.fetchone()[0]

                # 2. Tenta inserir a plataforma. Se a combinação streamer_id/platform_name já existir,
                # atualiza o token e a data de atualização.
                cur.execute(
                    "INSERT INTO streamer_platform (streamer_id, platform_id, platform_name, token) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (streamer_id, platform_name) DO UPDATE SET token = EXCLUDED.token, updated_at = NOW()",
                    (streamer_id, platform_id, platform_name, json.dumps(token_data))
                )
            # 3. Comita a transação apenas no final.
            self.conn.commit()

        except psycopg2.Error as e:
            self.conn.rollback()
            raise RuntimeError(f"Failed to insert/update token: {e}")

    def refresh_token(self, token_data: dict, platform_id : str) -> None:
        try:
            #Insere token em formato JSON no banco de dados
            with self.conn.cursor() as cur:
                cur.execute(
                    """UPDATE streamer_platform 
                    SET token = %s 
                    WHERE platform_id = %s""",
                    (json.dumps(token_data), platform_id)
                )
            self.conn.commit()

        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Failed to refresh token: {e}")

    def select_token_by_platform(self, platform_id: str):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT token
                FROM streamer_platform
                WHERE platform_id = %s
            """, (platform_id,))
            row = cur.fetchone()
            if row:
                import json
                return json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return None

    def select_streamer_id(self, guild_id: str):
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT id FROM streamer WHERE guild_id = %s", (guild_id,))
                result = cur.fetchone()
                if result:
                    return int(result[0])
                return None  # não encontrou streamer
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Erro ao pegar o streamer_id: {e}")

    def select_streamer_id_by_platform_id(self, platform_id: str):
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT streamer_id FROM streamer_platform WHERE platform_id = %s", (platform_id,))
                result = cur.fetchone()
                if result:
                    return int(result[0])
                return None  # não encontrou streamer
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Erro ao pegar o streamer_id: {e}")

    def select_app_access_token(self):
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT token_data FROM app_access_token ORDER BY expires_at DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row:
                    import json
                    # token está salvo como JSONB ou TEXT, garante que sempre retorna dict
                    return json.loads(row[0]) if isinstance(row[0], str) else row[0]
                return None  # não encontrou token
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Erro ao pegar o App Access Token: {e}")

    def select_valid_app_access_token(self, margem_segundos: int = 300):
        """
        Igual ao select_app_access_token, mas só devolve o token se ele ainda
        não expirou. A margem evita pegar um token que vence no meio da requisição.
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT token_data
                    FROM app_access_token
                    WHERE expires_at > NOW() + (%s * interval '1 second')
                    ORDER BY expires_at DESC
                    LIMIT 1
                    """,
                    (margem_segundos,)
                )
                row = cur.fetchone()
                if row:
                    return json.loads(row[0]) if isinstance(row[0], str) else row[0]
                return None  # não tem token válido, quem chamou que gere um novo
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Erro ao pegar o App Access Token válido: {e}")

    def insert_bot_token(self, token_data: dict, streamer_id: int, platform_id: str, platform_name: str = "twitch_bot"):
        """
        Grava o token da conta do bot.

        Usa um platform_name próprio ('twitch_bot') para não bater na UNIQUE
        (streamer_id, platform_name) da linha do streamer, e não toca na tabela
        streamer — o bot não é um streamer, é a conta que fala no chat.
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO streamer_platform (streamer_id, platform_id, platform_name, token) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (platform_id) DO UPDATE SET token = EXCLUDED.token, updated_at = NOW()",
                    (streamer_id, platform_id, platform_name, json.dumps(token_data))
                )
            self.conn.commit()

        except psycopg2.Error as e:
            self.conn.rollback()
            raise RuntimeError(f"Failed to insert/update bot token: {e}")

    def insert_eventsub_subscription(
                self,
                streamer_id: int,
                platform_id: str,
                subscription_id: str,
                status: str,
                type_: str,
                transport_callback: str,
                webhook_secret: str,
                expires_at: str  # ISO datetime ou datetime object
    ):
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO twitch_eventsub_subscription
                    (streamer_id, platform_id, subscription_id, status, type, transport_callback, webhook_secret, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (subscription_id)
                    DO UPDATE SET
                    status = EXCLUDED.status,
                    type = EXCLUDED.type,
                    transport_callback = EXCLUDED.transport_callback,
                    webhook_secret = EXCLUDED.webhook_secret,
                    expires_at = EXCLUDED.expires_at
                    RETURNING id
                    """,(streamer_id,platform_id,subscription_id,status,type_,transport_callback,webhook_secret,expires_at))
                subscription_id_db = cur.fetchone()[0]
                self.conn.commit()
                return subscription_id_db

        except psycopg2.Error as e:
            self.conn.rollback()
            raise RuntimeError(f"Failed to insert/update EventSub subscription: {e}")

    def insert_app_access_token(self, token_data: dict):
        try:
            with self.conn.cursor() as cur:
                # Calcula a data de expiração com base no 'expires_in' retornado pela Twitch
                expires_at = f"NOW() + interval '{token_data.get('expires_in', 3600)} seconds'"

                # Insere ou atualiza
                cur.execute(
                    f"""
                    INSERT INTO app_access_token (token_data, expires_at)
                    VALUES (%s, {expires_at})
                    ON CONFLICT (id)
                    DO UPDATE SET token_data = EXCLUDED.token_data,
                                  expires_at = EXCLUDED.expires_at,
                                  created_at = NOW()
                    """,
                    (json.dumps(token_data),)
                )
            self.conn.commit()
        except psycopg2.Error as e:
            self.conn.rollback()
            raise RuntimeError(f"Failed to insert/update App Access Token: {e}")
