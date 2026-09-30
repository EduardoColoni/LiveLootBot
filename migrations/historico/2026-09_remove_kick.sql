-- ============================================================================
-- Remoção da plataforma Kick do banco de dados.
--
-- Banco alvo: live_loot_bot_test (é o banco com o schema atual: authenticated_users,
-- streamer_platform, etc). Confira o DB_NAME do seu .env antes de rodar.
--
-- Rode DEPOIS de subir o código da branch remove_kick. O código já não lê mais
-- nenhuma dessas colunas/tabelas, então ele funciona antes e depois deste script.
--
-- BACKUP ANTES (é irreversível):
--   pg_dump -U postgres -d live_loot_bot_test > backup_antes_de_remover_kick.sql
--
-- A ORDEM DOS PASSOS IMPORTA. Existe esta FK:
--   kick_eventsub_subscriptions.platform_id -> streamer_platform.platform_id
-- Se apagar as linhas de streamer_platform antes de dropar a tabela da Kick,
-- o Postgres barra com "violates foreign key constraint".
-- ============================================================================

BEGIN;

-- 1. Tabela de inscrições de webhook da Kick.
--    O DROP TABLE leva junto a PK, as duas UNIQUE, a sequence e a FK acima.
DROP TABLE IF EXISTS kick_eventsub_subscriptions;

-- 2. Tokens/cadastro do streamer na Kick.
--    Só é possível depois do passo 1, por causa da FK.
DELETE FROM streamer_platform WHERE platform_name = 'kick';

-- 3. Colunas de viewer da Kick.
--    Não têm índice, FK nem constraint apontando para elas: o DROP é direto.
ALTER TABLE authenticated_users DROP COLUMN IF EXISTS kick_id;
ALTER TABLE authenticated_users DROP COLUMN IF EXISTS kick_user_name;

COMMIT;

-- ============================================================================
-- PASSO 4 - OPCIONAL, e destrutivo: viewers que só existiam na Kick.
--
-- Quem se autenticou apenas na Kick fica com twitch_id NULL. Esses registros
-- continuam sendo sorteados por raffle_viewer(), mas nunca recebem a mensagem
-- de claim (não têm conta na Twitch), então gastam rodadas do sorteio à toa.
--
-- Veja quantos são antes de decidir:
--     SELECT COUNT(*) FROM authenticated_users WHERE twitch_id IS NULL;
--
-- Se quiser limpar (eles podem se autenticar de novo pelo comando !autenticar):
--     DELETE FROM authenticated_users WHERE twitch_id IS NULL;
-- ============================================================================

-- Conferência pós-execução: as três consultas abaixo devem voltar vazias.
--   SELECT * FROM information_schema.tables  WHERE table_name = 'kick_eventsub_subscriptions';
--   SELECT * FROM information_schema.columns WHERE table_name = 'authenticated_users' AND column_name LIKE 'kick%';
--   SELECT * FROM streamer_platform WHERE platform_name = 'kick';
