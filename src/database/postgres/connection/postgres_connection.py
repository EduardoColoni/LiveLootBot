from .connection_options_postgres import connection_options_postgres
from psycopg2 import InterfaceError, OperationalError, pool

class PostgresPool:
    __pool = None

    @classmethod
    def init_pool(cls, minconn = 1, maxconn = 5):
        if cls.__pool is None:
            cls.__pool = pool.SimpleConnectionPool(
                minconn,
                maxconn,
                host=connection_options_postgres['HOST'],
                port=connection_options_postgres['PORT'],
                user=connection_options_postgres['USER'],
                password=connection_options_postgres['PASSWORD'],
                database=connection_options_postgres['DB_NAME']
            )

    @classmethod
    def get_conn(cls, tentativas = 3):
        if cls.__pool is None:
            raise RuntimeError("Connection pool not initialized")

        # O banco pode ter derrubado a conexão sem o pool ficar sabendo: o
        # container do postgres dormiu, reiniciou, ou o servidor cortou por
        # inatividade. Sem testar antes de entregar, a primeira requisição
        # depois disso morre com "server closed the connection unexpectedly".
        for _ in range(tentativas):
            conn = cls.__pool.getconn()

            if cls.__esta_viva(conn):
                print("Conexão realizada ao banco")
                return conn

            print("AVISO: conexão obsoleta descartada, pegando outra")
            cls.__pool.putconn(conn, close=True)

        raise RuntimeError("Não foi possível pegar uma conexão viva com o banco")

    @staticmethod
    def __esta_viva(conn):
        """Ping barato para saber se a conexão ainda existe do lado do banco."""
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.rollback()  # o SELECT abre transação; não devolve a conexão presa nela
            return True
        except (OperationalError, InterfaceError):
            return False

    @classmethod
    def release_conn(cls, conn):
        if cls.__pool:
            cls.__pool.putconn(conn)
            print("Conexão retornada ao pool")

    @classmethod
    def close_all(cls):
        if cls.__pool:
            cls.__pool.closeall()
            print("Fechada todas conexões com o banco")

