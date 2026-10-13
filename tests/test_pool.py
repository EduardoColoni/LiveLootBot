"""
Pool de conexões: quando o banco derruba as conexões (contêiner reiniciou,
corte por inatividade), a próxima requisição tem que receber uma conexão viva
em vez de morrer com "server closed the connection unexpectedly".
"""
import pytest

from conftest import BANCO_TESTE, _conectar
from src.database.postgres.connection.postgres_connection import PostgresPool


def _derrubar_conexoes_do_banco():
    admin = _conectar("postgres")
    with admin.cursor() as cur:
        cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                    (BANCO_TESTE,))
    admin.close()


@pytest.mark.parametrize("conexoes_em_uso", [1, 5])
def test_conexao_derrubada_e_trocada_por_uma_viva(conexoes_em_uso):
    # Usa várias conexões ao mesmo tempo e devolve todas ao pool
    abertas = [PostgresPool.get_conn() for _ in range(conexoes_em_uso)]
    for c in abertas:
        PostgresPool.release_conn(c)

    _derrubar_conexoes_do_banco()

    conn = PostgresPool.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
    finally:
        PostgresPool.release_conn(conn)
