from fastapi.templating import Jinja2Templates

# Esta é uma instância única que será importada por qualquer rota que precisar dela
templates = Jinja2Templates(directory="src/api/templates")


ROTULOS = {"sucesso": "Tudo certo", "aviso": "Atenção", "erro": "Algo deu errado"}


def pagina(request, tipo: str, titulo: str, *mensagens, detalhe: str = None, status_code: int = 200):
    """
    Página mostrada no navegador ao fim de cada autorização (templates/pagina.html).

    `tipo` é "sucesso", "aviso" ou "erro". Cada item de `mensagens` vira um parágrafo e
    `detalhe` vai numa caixa à parte (ex.: a resposta da Twitch). Tudo é escapado pelo
    Jinja; para destacar um trecho, use Markup("... <strong>{}</strong>").format(valor),
    que escapa o valor.
    """
    return templates.TemplateResponse(
        request,
        "pagina.html",
        {"tipo": tipo, "rotulo": ROTULOS[tipo], "titulo": titulo, "mensagens": mensagens, "detalhe": detalhe},
        status_code=status_code,
    )
