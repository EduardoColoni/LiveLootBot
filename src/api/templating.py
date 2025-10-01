from fastapi.templating import Jinja2Templates

# Esta é uma instância única que será importada por qualquer rota que precisar dela
templates = Jinja2Templates(directory="src/api/templates")