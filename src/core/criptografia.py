"""
Cifragem dos tokens da Twitch antes de irem para o banco.

Usa Fernet (biblioteca cryptography): AES-128-CBC com HMAC-SHA256 no esquema
encrypt-then-MAC. O IV é gerado a cada cifragem e o HMAC garante que um valor
adulterado no banco seja recusado em vez de decifrado errado.

No banco o token fica num envelope JSON, para caber na coluna jsonb:

    {"alg": "fernet", "kid": 1, "ct": "gAAAAAB..."}

- alg: esquema usado, para saber como abrir o envelope
- kid: qual chave cifrou; prepara uma futura troca de chave
- ct:  o token cifrado (o dicionário inteiro devolvido pela Twitch)

A chave fica no src/.env (TOKEN_ENCRYPTION_KEY), fora do banco. Isso protege
contra quem tem acesso só ao banco ou a um backup dele, não contra quem tem
acesso ao servidor da aplicação, que precisa da chave para usar os tokens.
"""
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from src.core.config import crypto_config, twitch

ALGORITMO = "fernet"
KID_ATUAL = 1

_fernet = None


class TokenSemCriptografiaError(RuntimeError):
    """O banco tem um token gravado antes da criptografia existir."""


def _get_fernet() -> Fernet:
    # Criado só no primeiro uso: quem não mexe com tokens (o bot, por exemplo)
    # não precisa da chave para subir.
    global _fernet
    if _fernet is None:
        chave = crypto_config["TOKEN_ENCRYPTION_KEY"]
        if not chave:
            raise RuntimeError(
                "TOKEN_ENCRYPTION_KEY não definida no src/.env. Gere uma com: "
                "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        try:
            _fernet = Fernet(chave.encode())
        except ValueError:
            raise RuntimeError(
                "TOKEN_ENCRYPTION_KEY inválida: precisa ser uma chave Fernet "
                "(32 bytes em base64 url-safe, 44 caracteres)."
            )
    return _fernet


def cifrar_token(token_data: dict) -> str:
    """Recebe o dicionário do token e devolve o envelope pronto para o jsonb."""
    ct = _get_fernet().encrypt(json.dumps(token_data).encode()).decode()
    return json.dumps({"alg": ALGORITMO, "kid": KID_ATUAL, "ct": ct})


def decifrar_token(valor, origem: str = "token") -> dict:
    """
    Recebe o que veio da coluna jsonb e devolve o dicionário do token.

    Se o valor não estiver no envelope, é um token antigo em texto puro.
    Ele é recusado em vez de usado: o sistema não aceita token sem cifra.
    """
    envelope = json.loads(valor) if isinstance(valor, str) else valor

    if not (isinstance(envelope, dict) and envelope.get("alg") == ALGORITMO and "ct" in envelope):
        raise TokenSemCriptografiaError(
            f"O {origem} está gravado sem criptografia. Refaça a autenticação "
            f"para gravá-lo de novo, já cifrado."
        )

    if envelope.get("kid") != KID_ATUAL:
        raise RuntimeError(f"O {origem} foi cifrado com uma chave desconhecida (kid={envelope.get('kid')}).")

    try:
        return json.loads(_get_fernet().decrypt(envelope["ct"].encode()))
    except InvalidToken:
        # Ou a chave do .env mudou, ou o valor no banco foi alterado
        raise RuntimeError(
            f"Não foi possível decifrar o {origem}: a TOKEN_ENCRYPTION_KEY não é a mesma "
            f"que o cifrou, ou o valor no banco foi alterado. Refaça a autenticação."
        )


def get_webhook_secret() -> str:
    """Segredo do HMAC do EventSub, lido do .env. A Twitch exige de 10 a 100 caracteres."""
    segredo = twitch["WEBHOOK_SECRET"]
    if not segredo or not 10 <= len(segredo) <= 100:
        raise RuntimeError(
            "TWITCH_WEBHOOK_SECRET ausente ou inválida no src/.env (precisa ter de 10 a 100 caracteres). "
            "Gere uma com: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return segredo


def impressao_digital_segredo(segredo: str) -> str:
    """
    Identifica o segredo sem revelá-lo: um pedaço do SHA-256.

    É o que vai para a coluna webhook_secret. Serve para saber se uma inscrição
    do EventSub foi criada com o segredo atual ou com um antigo.
    """
    return "sha256:" + hashlib.sha256(segredo.encode()).hexdigest()[:16]
