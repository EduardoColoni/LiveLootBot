import os
from dotenv import load_dotenv

load_dotenv()

discord_config = {
    'TOKEN': str(os.getenv('DISCORD_TOKEN')),
}

twitch = {
    'CLIENT_ID': str(os.getenv('CLIENT_ID')),
    'CLIENT_SECRET': str(os.getenv('CLIENT_SECRET')),
    'REDIRECT_URI_STREAMER': os.getenv('REDIRECT_URI_STREAMER', 'http://localhost:8000/twitch_callback'),
    'REDIRECT_URI_VIEWER': os.getenv('REDIRECT_URI_VIEWER', 'http://localhost:8000/twitch_callback'),
    'TWITCH_URL' : os.getenv('TWITCH_URL', 'https://id.twitch.tv/oauth2'),
}

kick = {
    'CLIENT_ID_KICK': str(os.getenv('CLIENT_ID_KICK')),
    'CLIENT_SECRET_KICK': str(os.getenv('CLIENT_SECRET_KICK')),
    'REDIRECT_URI_STREAMER_KICK': os.getenv('REDIRECT_URI_STREAMER_KICK', 'http://localhost:8000/twitch_callback'),
    'REDIRECT_URI_VIEWER_KICK': os.getenv('REDIRECT_URI_VIEWER_KICK', 'http://localhost:8000/twitch_callback'),
    'KICK_URL' : os.getenv('KICK_URL', 'https://id.kick.com/oauth'),
}


connection_options_postgres = {
    'HOST': os.getenv('DB_HOST', 'localhost'),
    'PORT': int(os.getenv('DB_PORT', 5432)),
    'USER': os.getenv('DB_USER', 'postgres' ),
    'PASSWORD': os.getenv('DB_PASSWORD', 'postgres'),
    'DB_NAME': os.getenv('DB_NAME', 'postgres')
}

connection_options_redis = {
    'HOST': os.getenv('REDIS_HOST', 'localhost'),
    'PORT': int(os.getenv('REDIS_PORT', 6379)),
    'DB': int(os.getenv('REDIS_DB', 0))
}

api_config = {
    'URL_BASE': os.getenv('URL_BASE', 'localhost')
}