from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles

from src.api.routes.kick_auth_route import kick_setup_auth_routes
from src.api.routes.kick_chatters_routes import kick_setup_chatters_routes
from src.api.routes.overlays import setup_overlays_routes
from src.api.services.kick_event_sub import kick_event_sub_routes
from src.api.services.twitch_event_sub import twitch_event_sub_routes
from src.database.postgres.connection.postgres_connection import PostgresPool
from src.api.routes.twitch_auth_route import setup_auth_routes
from src.api.routes.twitch_chatters_routes import setup_chatters_routes

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    PostgresPool.init_pool(minconn=1, maxconn=5)
    print("Conexão realizada ao banco (pool inicializado)")

    yield  # app executa aqui

    # Shutdown
    PostgresPool.close_all()
    print("Fechada todas conexões com o banco")


app = FastAPI(lifespan=lifespan)

# Servir arquivos estáticos (CSS, JS, Imagens)
app.mount("/static", StaticFiles(directory="src/api/static"), name="static")

# Rotas são registradas fora do lifespan porque não precisam da conexão diretamente
app.include_router(setup_auth_routes())
app.include_router(twitch_event_sub_routes())
app.include_router(setup_chatters_routes())
app.include_router(kick_setup_auth_routes())
app.include_router(kick_setup_chatters_routes())
app.include_router(kick_event_sub_routes())
app.include_router(setup_overlays_routes())
