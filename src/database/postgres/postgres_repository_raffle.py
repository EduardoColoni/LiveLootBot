class PostgresRepositoryRaffle:
    def __init__(self, conn):
        self.conn = conn  # Usa a conexão recebida

    def insert_items(self, item: str, weight: int, raffle_id: int, guild_id: str):
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT insert_items(%s, %s, %s, %s)", (item, weight, raffle_id, guild_id,))
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Erro ao inserir itens: {e}")

    def make_raffle(self, guild_id: str):
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT * FROM make_raffle(%s)", (guild_id,))
                result = cur.fetchone()
                if result and all(result):
                    return result
                else:
                    return None
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Failed to get raffle item IDs: {e}")

    def make_raffle_id(self, guild_id: str):
        try:
            with self.conn.cursor() as cur:
                # Busca streamer_id
                cur.execute("SELECT id FROM streamer WHERE guild_id = %s", (guild_id,))
                streamer_row = cur.fetchone()

                if not streamer_row:
                    return None

                streamer_id = streamer_row[0]

                # Busca o próximo raffle_id
                cur.execute("""
                    SELECT COALESCE(MAX(raffle_id), 0) + 1 
                    FROM raffle_items 
                    WHERE streamer_id = %s
                """, (streamer_id,))

                return cur.fetchone()[0]

        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Failed to generate raffle ID: {e}")

    def update_item(self, winner_name: str, item_id: int, raffle_id: int):
        try:
            with self.conn.cursor() as cur:
                cur.execute("UPDATE raffle_items SET winner = %s, updated_at = NOW() WHERE id = %s AND raffle_id = %s;", (winner_name, item_id, raffle_id,))
            self.conn.commit()

        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Failed to make raffle ID: {e}")

    def get_last_raffle_id(self, received_streamer_id: int):
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT MAX(raffle_id) FROM raffle_items WHERE streamer_id = %s", (received_streamer_id,))
                raffle_id = cur.fetchone()[0]
                return int(raffle_id) if raffle_id else 0

        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Erro ao pegar o ultimo id de sorteio: {e}")

    def get_streamer_id(self, guild_id: str):
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT id FROM streamer WHERE guild_id = %s", (guild_id,))
                streamer_id = cur.fetchone()[0]
                return int(streamer_id) if streamer_id else 0

        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Erro ao pegar o streamer id: {e}")

    #Atualmente não usada em lugar algum, ainda estou pensando se tiro ela ou não
    def verify_item_list(self, raffle_id: int):
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT item FROM raffle_items WHERE raffle_id = %s AND winner IS NULL;", (raffle_id,))
                items = cur.fetchall()
                return items #Vai retornar uma lista dos itens com winner vazio, senão tiver nenhum vai retornar uma tupla vazia []
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Failed to verify item: {e}")

    def select_streamer_platforms(self, streamer_id: int):
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT sp.platform_name, sp.platform_id
                    FROM streamer_platform sp
                    JOIN streamer s ON s.id = sp.streamer_id
                    WHERE s.id = %s
                    """,
                    (streamer_id,)
                )
                rows = cur.fetchall()

                if not rows:
                    return None

                # transforma em dicionário com chave = platform_name
                result = {
                    row[0]: {
                        "platform_id": row[1]
                    }
                    for row in rows
                }
                return result

        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Erro ao buscar plataformas do streamer: {e}")

    def raffle_viewer(self, streamer_id : int):
        try:
            with self.conn.cursor() as cur:
                # Colunas nomeadas (e não SELECT *) para o resultado não depender da ordem
                # das colunas da tabela. Para uma plataforma nova, basta adicionar as
                # colunas dela aqui e no dicionário abaixo.
                cur.execute(
                    """
                    SELECT discord_id, discord_user_name, twitch_id, twitch_user_name
                    FROM authenticated_users
                    WHERE streamer_id = %s
                    ORDER BY RANDOM()
                    LIMIT 1;
                    """,
                    (streamer_id,)
                )
                viewer = cur.fetchall()

                if not viewer:
                    return None

                row = viewer[0]

                result = {
                    "discord": {
                        "id": row[0],
                        "user_name": row[1]
                    },
                    "twitch": {
                        "id": row[2],
                        "user_name": row[3]
                    }
                }

                return result

        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Erro ao buscar plataformas do streamer: {e}")