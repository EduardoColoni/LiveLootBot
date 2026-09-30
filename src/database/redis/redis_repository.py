from redis import Redis

class RedisRepository:
    def __init__(self, redis_conn: Redis) -> None:
        self.__redis_conn = redis_conn

    def insert(self, key: str, value: any) -> None:
        self.__redis_conn.set(key, value)

    def get(self, key: str) -> any:
        value = self.__redis_conn.get(key)
        if value:
            return value.decode('utf-8')

    def delete(self, key: str) -> None:
        self.__redis_conn.delete(key)

    def insert_hash(self, key: str, field: str, value: any) -> None:
        self.__redis_conn.hset(key, field, value)

    def get_hash(self, key: str, field: str) -> any:
        value = self.__redis_conn.hget(key, field)
        if value:
            return value.decode('utf-8')

    def insert_ex(self, key: str, value: any, ex: int) -> None:
        self.__redis_conn.set(key, value, ex=ex)

    def insert_hash_ex(self, key: str, field: str, value: any, ex: int) -> None:
        self.__redis_conn.hset(key, field, value)
        self.__redis_conn.expire(key, ex)

    # Insere mensagem em uma lista e aplica expiração

    def push_message_ex(self, broadcaster_id: str, user_name : str, ex: int = 120):
        key = f"chat:{broadcaster_id}"
        self.__redis_conn.lpush(key, user_name)  # adiciona no início da lista
        self.__redis_conn.expire(key, ex)  # garante que expira em X segundos
        print("Conteúdo inserido no Redis")

    # Recupera todas mensagens de um broadcaster

    def get_messages(self, broadcaster_id: str):
        key = f"chat:{broadcaster_id}"
        return self.__redis_conn.lrange(key, 0, -1)  # retorna lista completa

    # Recupera só a mais recente (índice 0)

    def get_latest_message(self, broadcaster_id: str):
        key = f"chat:{broadcaster_id}"
        result = self.__redis_conn.lindex(key, 0)
        return result.decode("utf-8") if result else None