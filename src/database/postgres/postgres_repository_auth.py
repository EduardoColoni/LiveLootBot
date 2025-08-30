import json

import psycopg2
from psycopg2 import errorcodes

class PostgresRepositoryAuth:
    def __init__(self, conn):
        self.conn = conn  # Usa a conexão recebida

    def insert_token(self, token_data: dict, streamer_id: str, guild_id: str, streamer_name: str):
        try:
            #Insere token em formato JSON no banco de dados
            with self.conn.cursor() as cur:
                cur.execute("INSERT INTO streamer (token, streamer_id, guild_id, streamer_name) VALUES (%s, %s, %s, %s)", (json.dumps(token_data), streamer_id, guild_id, streamer_name))
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Failed to insert token: {e}")

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
                    "INSERT INTO streamer_platform (streamer_id, guild_id, platform_id, platform_name, token) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (streamer_id, platform_name) DO UPDATE SET token = EXCLUDED.token, updated_at = NOW()",
                    (streamer_id, guild_id, platform_id, platform_name, json.dumps(token_data))
                )
            # 3. Comita a transação apenas no final.
            self.conn.commit()

        except psycopg2.Error as e:
            self.conn.rollback()
            raise RuntimeError(f"Failed to insert/update token: {e}")

    def refresh_token(self, token_data: dict) -> None:
        try:
            #Insere token em formato JSON no banco de dados
            with self.conn.cursor() as cur:
                cur.execute("UPDATE streamer SET token = %s WHERE id = (SELECT id FROM streamer ORDER BY id DESC LIMIT 1)", (json.dumps(token_data),))
            self.conn.commit()

        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Failed to refresh token: {e}")

    def select_token_by_streamer(self, streamer_id: str):
        with self.conn.cursor() as cur:
            cur.execute("SELECT token FROM streamer WHERE streamer_id = %s", (streamer_id,))
            row = cur.fetchone()
            if row:
                import json
                return json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return None
