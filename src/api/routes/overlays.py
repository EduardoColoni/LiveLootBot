from fastapi import Request, APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from src.api.templating import templates

from src.core.config import api_config


class OverlaysController:
    def __init__(self):
        self.router = APIRouter()
        # Adicionei {winner_name} para tornar a rota dinâmica
        self.router.add_api_route(
            "/overlays/winner/{winner_name}", # Rota agora aceita um parâmetro
            self.send_winner,
            methods=["GET"],
            response_class=HTMLResponse # A resposta será um HTML renderizado
        )

    def send_winner(self, request: Request, winner_name: str):
        return templates.TemplateResponse(
            "obs_overlay.html", # Nome do arquivo na pasta /templates
            {
                "request": request,
                "winner_name": winner_name # Passa os dados para o HTML
            }
        )

def setup_overlays_routes():
    controller = OverlaysController()
    return controller.router
