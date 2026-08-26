-- Remoção da plataforma Kick do banco de dados.
--
-- Rode DEPOIS de subir o código desta branch (o código já não lê mais nenhuma
-- dessas colunas/tabelas, então ele continua funcionando antes e depois daqui).
--
-- ATENÇÃO: faça backup antes. Os dados de Kick são apagados de forma definitiva.
--   pg_dump -U <user> -d <banco> > backup_antes_de_remover_kick.sql

BEGIN;

-- 1. Tabela de inscrições de webhook da Kick (equivalente à twitch_eventsub_subscription)
DROP TABLE IF EXISTS kick_eventsub_subscriptions;

-- 2. Tokens/cadastros de streamer na Kick
DELETE FROM streamer_platform WHERE platform_name = 'kick';

-- 3. Colunas de viewer da Kick
ALTER TABLE authenticated_users DROP COLUMN IF EXISTS kick_id;
ALTER TABLE authenticated_users DROP COLUMN IF EXISTS kick_user_name;

COMMIT;

-- Depois de rodar, confira se a function make_raffle() (que vive dentro do banco
-- e não está versionada aqui) referencia alguma coluna da Kick:
--   SELECT prosrc FROM pg_proc WHERE proname = 'make_raffle';
