--
-- Schema completo do LiveLootBot (banco live_loot_bot_test).
--
-- Gerado com:
--   pg_dump -U postgres -d live_loot_bot_test --schema-only --no-owner --no-privileges
--
-- Este arquivo cria tudo do zero: tipos, tabelas, sequences, constraints, índices
-- e as duas funções de negócio (insert_items e make_raffle). Não cria o banco em si
-- nem contém dados.
--
-- Para aplicar à mão:
--   createdb -U postgres live_loot_bot_test
--   psql -U postgres -d live_loot_bot_test -f migrations/000_schema_inicial.sql
--
-- Já reflete a remoção da Kick; a migração correspondente está em historico/.
--
--
-- PostgreSQL database dump
--


-- Dumped from database version 16.14
-- Dumped by pg_dump version 16.14

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: eventsub_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.eventsub_status AS ENUM (
    'enabled',
    'pending',
    'disabled'
);


--
-- Name: insert_items(character varying, integer, integer, character varying); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.insert_items(recived_item character varying, recived_weigth integer, recived_raffle_id integer, recived_guild_id character varying) RETURNS void
    LANGUAGE plpgsql
    AS $$

DECLARE
	streamer_id_done integer;

BEGIN

	SELECT id INTO streamer_id_done 
	FROM streamer 
	WHERE guild_id = recived_guild_id;

    -- Insere o novo item com o raffle_id incrementado.
    INSERT INTO raffle_items (item, weight, raffle_id, streamer_id) 
    VALUES (recived_item, recived_weigth, recived_raffle_id, streamer_id_done);

END;
$$;


--
-- Name: make_raffle(character varying); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.make_raffle(recived_guild_id character varying) RETURNS TABLE(selected_item_id integer, selected_raffle_round_id integer, selected_item_name character varying)
    LANGUAGE plpgsql
    AS $$
DECLARE
    recived_streamer_id INT;
    v_selected_item_id INT; -- Use um nome diferente para evitar conflito com o nome da coluna de retorno
	v_selected_item_name VARCHAR;
    v_selected_raffle_round_id INT; -- Use um nome diferente para evitar conflito com o nome da coluna de retorno
BEGIN
    -- 1. Busca o streamer_id com base no guild_id recebido
    SELECT id INTO recived_streamer_id FROM streamer WHERE guild_id = recived_guild_id;

    -- 2. Verifica se o streamer foi encontrado. Se não, retorna uma tabela vazia.
    IF recived_streamer_id IS NULL THEN
        RETURN; -- Retorna uma tabela vazia quando o streamer não é encontrado
    END IF;

    -- 3. Executa a lógica do sorteio usando o recived_streamer_id
    -- Note: A lógica do RANDOM() dentro do WHERE pode ser ineficiente para grandes conjuntos de dados.
    -- Considere refatorar para uma abordagem mais performática se o desempenho for um problema.
    SELECT id, raffle_id, item
    INTO v_selected_item_id, v_selected_raffle_round_id, v_selected_item_name -- Atribui aos v_selected_...
    FROM raffle_items
    WHERE streamer_id = recived_streamer_id
      AND raffle_id = (SELECT MAX(raffle_id) FROM raffle_items WHERE streamer_id = recived_streamer_id)
      AND winner IS NULL
      AND (
        SELECT RANDOM() * SUM(weight)
        FROM raffle_items
        WHERE streamer_id = recived_streamer_id
          AND winner IS NULL
          AND raffle_id = (SELECT MAX(raffle_id) FROM raffle_items WHERE streamer_id = recived_streamer_id)
      ) <= (
        SELECT SUM(weight)
        FROM raffle_items AS r2
        WHERE r2.id <= raffle_items.id
          AND r2.streamer_id = recived_streamer_id
          AND r2.winner IS NULL
          AND r2.raffle_id = (SELECT MAX(raffle_id) FROM raffle_items WHERE streamer_id = recived_streamer_id)
      )
    ORDER BY id
    LIMIT 1;

    -- 4. Se um item foi selecionado, adicione-o à tabela de resultados
    IF v_selected_item_id IS NOT NULL THEN
        selected_item_id := v_selected_item_id; -- Atribui aos nomes das colunas de retorno
		selected_item_name := v_selected_item_name;
        selected_raffle_round_id := v_selected_raffle_round_id; -- Atribui aos nomes das colunas de retorno
        RETURN NEXT; -- Adiciona a linha atual ao conjunto de resultados
    END IF;

    RETURN; -- Finaliza a função e retorna todas as linhas acumuladas
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: app_access_token; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.app_access_token (
    id bigint NOT NULL,
    token_data jsonb NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE app_access_token; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.app_access_token IS 'Tabela que armazena o App Access Token da Twitch para criar EventSub subscriptions.';


--
-- Name: COLUMN app_access_token.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.app_access_token.id IS 'Identificador único do registro.';


--
-- Name: COLUMN app_access_token.token_data; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.app_access_token.token_data IS 'Dados do App Access Token retornados pela Twitch, cifrados com Fernet pela aplicação (envelope JSON: alg, kid, ct).';


--
-- Name: COLUMN app_access_token.expires_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.app_access_token.expires_at IS 'Data e hora de expiração do token.';


--
-- Name: COLUMN app_access_token.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.app_access_token.created_at IS 'Data e hora da criação do registro.';


--
-- Name: app_access_token_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.app_access_token_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: app_access_token_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.app_access_token_id_seq OWNED BY public.app_access_token.id;


--
-- Name: authenticated_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.authenticated_users (
    id bigint NOT NULL,
    streamer_id bigint NOT NULL,
    discord_id character varying(255) NOT NULL,
    twitch_id character varying(255),
    discord_user_name character varying(255),
    twitch_user_name character varying(255),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE authenticated_users; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.authenticated_users IS 'Tabela que armazena usuários autenticados e seus vínculos com streamers.';


--
-- Name: COLUMN authenticated_users.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.authenticated_users.id IS 'Identificador único e incremental da tabela.';


--
-- Name: COLUMN authenticated_users.streamer_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.authenticated_users.streamer_id IS 'Chave estrangeira para a tabela streamer.';


--
-- Name: COLUMN authenticated_users.discord_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.authenticated_users.discord_id IS 'ID do usuário do Discord.';


--
-- Name: COLUMN authenticated_users.twitch_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.authenticated_users.twitch_id IS 'ID da conta do Twitch do usuário.';


--
-- Name: COLUMN authenticated_users.discord_user_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.authenticated_users.discord_user_name IS 'Nome de usuário do Discord.';


--
-- Name: COLUMN authenticated_users.twitch_user_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.authenticated_users.twitch_user_name IS 'Nome de usuário do Twitch.';


--
-- Name: COLUMN authenticated_users.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.authenticated_users.created_at IS 'Data e hora da criação do registro.';


--
-- Name: COLUMN authenticated_users.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.authenticated_users.updated_at IS 'Data e hora da última atualização do registro.';


--
-- Name: authenticated_users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.authenticated_users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: authenticated_users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.authenticated_users_id_seq OWNED BY public.authenticated_users.id;


--
-- Name: raffle_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.raffle_items (
    id bigint NOT NULL,
    streamer_id bigint NOT NULL,
    raffle_id bigint NOT NULL,
    item character varying(255) NOT NULL,
    weight integer DEFAULT 50,
    winner character varying(50),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE raffle_items; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.raffle_items IS 'Itens de sorteio vinculados a um streamer e ao seu sorteio.';


--
-- Name: COLUMN raffle_items.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.raffle_items.id IS 'Identificador único e incremental da tabela.';


--
-- Name: COLUMN raffle_items.streamer_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.raffle_items.streamer_id IS 'Chave estrangeira para a tabela streamer. Deletar um streamer irá remover todos os seus itens de sorteio.';


--
-- Name: COLUMN raffle_items.raffle_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.raffle_items.raffle_id IS 'Identificador incremental dos sorteios. O código é responsavel por controlar o valor desse campo';


--
-- Name: COLUMN raffle_items.item; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.raffle_items.item IS 'Descrição do item do sorteio.';


--
-- Name: COLUMN raffle_items.weight; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.raffle_items.weight IS 'Peso do item para o sorteio (maior peso = maior chance).';


--
-- Name: COLUMN raffle_items.winner; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.raffle_items.winner IS 'Vencedor do item.';


--
-- Name: COLUMN raffle_items.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.raffle_items.created_at IS 'Data e hora da criação do registro.';


--
-- Name: COLUMN raffle_items.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.raffle_items.updated_at IS 'Data e hora da última atualização do registro.';


--
-- Name: raffle_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.raffle_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: raffle_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.raffle_items_id_seq OWNED BY public.raffle_items.id;


--
-- Name: streamer; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.streamer (
    id bigint NOT NULL,
    streamer_name character varying(255) NOT NULL,
    guild_id character varying(50) NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE streamer; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.streamer IS 'Tabela para armazenar informações sobre streamers.';


--
-- Name: COLUMN streamer.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.streamer.id IS 'Identificador único e incremental da tabela.';


--
-- Name: COLUMN streamer.streamer_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.streamer.streamer_name IS 'Nome do streamer.';


--
-- Name: COLUMN streamer.guild_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.streamer.guild_id IS 'Identificador do servidor (guild) do Discord, único para cada entrada.';


--
-- Name: COLUMN streamer.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.streamer.created_at IS 'Data e hora da criação do registro.';


--
-- Name: COLUMN streamer.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.streamer.updated_at IS 'Data e hora da última atualização do registro.';


--
-- Name: streamer_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.streamer_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: streamer_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.streamer_id_seq OWNED BY public.streamer.id;


--
-- Name: streamer_platform; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.streamer_platform (
    id bigint NOT NULL,
    streamer_id bigint NOT NULL,
    platform_id character varying(255) NOT NULL,
    platform_name character varying(50) NOT NULL,
    token jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE streamer_platform; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.streamer_platform IS 'Tabela que vincula streamers a suas plataformas e tokens de acesso.';


--
-- Name: COLUMN streamer_platform.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.streamer_platform.id IS 'Identificador único e incremental da tabela.';


--
-- Name: COLUMN streamer_platform.streamer_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.streamer_platform.streamer_id IS 'Chave estrangeira para a tabela streamer. Deletar um streamer irá remover todos os seus vínculos de plataforma.';


--
-- Name: COLUMN streamer_platform.platform_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.streamer_platform.platform_id IS 'Identificador único global da conta do streamer na plataforma (ex: Twitch, Kick).';


--
-- Name: COLUMN streamer_platform.platform_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.streamer_platform.platform_name IS 'Nome da plataforma (ex: Twitch, Kick). Um mesmo streamer não pode ter duas vezes a mesma plataforma.';


--
-- Name: COLUMN streamer_platform.token; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.streamer_platform.token IS 'Token de acesso para a plataforma, cifrado com Fernet pela aplicação (envelope JSON: alg, kid, ct).';


--
-- Name: COLUMN streamer_platform.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.streamer_platform.created_at IS 'Data e hora da criação do registro.';


--
-- Name: COLUMN streamer_platform.updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.streamer_platform.updated_at IS 'Data e hora da última atualização do registro.';


--
-- Name: streamer_platform_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.streamer_platform_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: streamer_platform_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.streamer_platform_id_seq OWNED BY public.streamer_platform.id;


--
-- Name: twitch_eventsub_subscription; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.twitch_eventsub_subscription (
    id bigint NOT NULL,
    streamer_id bigint NOT NULL,
    platform_id character varying(100) NOT NULL,
    subscription_id character varying(255) NOT NULL,
    status public.eventsub_status NOT NULL,
    type character varying(255) NOT NULL,
    transport_callback character varying(255) NOT NULL,
    webhook_secret character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    expires_at timestamp with time zone NOT NULL
);


--
-- Name: TABLE twitch_eventsub_subscription; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.twitch_eventsub_subscription IS 'Tabela que armazena informações de assinaturas de eventos da Twitch.';


--
-- Name: COLUMN twitch_eventsub_subscription.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.twitch_eventsub_subscription.id IS 'Identificador único da assinatura.';


--
-- Name: COLUMN twitch_eventsub_subscription.streamer_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.twitch_eventsub_subscription.streamer_id IS 'Chave estrangeira para a tabela streamer. Deletar um streamer irá remover suas assinaturas de eventos.';


--
-- Name: COLUMN twitch_eventsub_subscription.platform_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.twitch_eventsub_subscription.platform_id IS 'Identificador da plataforma de streaming (ex: twitch).';


--
-- Name: COLUMN twitch_eventsub_subscription.subscription_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.twitch_eventsub_subscription.subscription_id IS 'ID da assinatura retornado pela Twitch.';


--
-- Name: COLUMN twitch_eventsub_subscription.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.twitch_eventsub_subscription.status IS 'Status da assinatura (enabled, pending, disabled).';


--
-- Name: COLUMN twitch_eventsub_subscription.type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.twitch_eventsub_subscription.type IS 'Tipo de evento assinado (ex: channel.chat.message).';


--
-- Name: COLUMN twitch_eventsub_subscription.transport_callback; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.twitch_eventsub_subscription.transport_callback IS 'URL do endpoint de callback.';


--
-- Name: COLUMN twitch_eventsub_subscription.webhook_secret; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.twitch_eventsub_subscription.webhook_secret IS 'Impressão digital (sha256:...) do segredo usado na criação da inscrição. Nunca o segredo em si.';


--
-- Name: COLUMN twitch_eventsub_subscription.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.twitch_eventsub_subscription.created_at IS 'Data e hora da criação da assinatura.';


--
-- Name: COLUMN twitch_eventsub_subscription.expires_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.twitch_eventsub_subscription.expires_at IS 'Data e hora de expiração da assinatura.';


--
-- Name: twitch_eventsub_subscription_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.twitch_eventsub_subscription_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: twitch_eventsub_subscription_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.twitch_eventsub_subscription_id_seq OWNED BY public.twitch_eventsub_subscription.id;


--
-- Name: app_access_token id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_access_token ALTER COLUMN id SET DEFAULT nextval('public.app_access_token_id_seq'::regclass);


--
-- Name: authenticated_users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authenticated_users ALTER COLUMN id SET DEFAULT nextval('public.authenticated_users_id_seq'::regclass);


--
-- Name: raffle_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.raffle_items ALTER COLUMN id SET DEFAULT nextval('public.raffle_items_id_seq'::regclass);


--
-- Name: streamer id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.streamer ALTER COLUMN id SET DEFAULT nextval('public.streamer_id_seq'::regclass);


--
-- Name: streamer_platform id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.streamer_platform ALTER COLUMN id SET DEFAULT nextval('public.streamer_platform_id_seq'::regclass);


--
-- Name: twitch_eventsub_subscription id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.twitch_eventsub_subscription ALTER COLUMN id SET DEFAULT nextval('public.twitch_eventsub_subscription_id_seq'::regclass);


--
-- Name: app_access_token app_access_token_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_access_token
    ADD CONSTRAINT app_access_token_pkey PRIMARY KEY (id);


--
-- Name: authenticated_users authenticated_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authenticated_users
    ADD CONSTRAINT authenticated_users_pkey PRIMARY KEY (id);


--
-- Name: authenticated_users authenticated_users_streamer_id_discord_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authenticated_users
    ADD CONSTRAINT authenticated_users_streamer_id_discord_id_key UNIQUE (streamer_id, discord_id);


--
-- Name: raffle_items raffle_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.raffle_items
    ADD CONSTRAINT raffle_items_pkey PRIMARY KEY (id);


--
-- Name: streamer streamer_guild_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.streamer
    ADD CONSTRAINT streamer_guild_id_key UNIQUE (guild_id);


--
-- Name: streamer streamer_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.streamer
    ADD CONSTRAINT streamer_pkey PRIMARY KEY (id);


--
-- Name: streamer_platform streamer_platform_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.streamer_platform
    ADD CONSTRAINT streamer_platform_pkey PRIMARY KEY (id);


--
-- Name: streamer_platform streamer_platform_platform_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.streamer_platform
    ADD CONSTRAINT streamer_platform_platform_id_key UNIQUE (platform_id);


--
-- Name: streamer_platform streamer_platform_streamer_id_platform_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.streamer_platform
    ADD CONSTRAINT streamer_platform_streamer_id_platform_name_key UNIQUE (streamer_id, platform_name);


--
-- Name: twitch_eventsub_subscription twitch_eventsub_subscription_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.twitch_eventsub_subscription
    ADD CONSTRAINT twitch_eventsub_subscription_pkey PRIMARY KEY (id);


--
-- Name: twitch_eventsub_subscription twitch_eventsub_subscription_subscription_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.twitch_eventsub_subscription
    ADD CONSTRAINT twitch_eventsub_subscription_subscription_id_key UNIQUE (subscription_id);


--
-- Name: idx_twitch_eventsub_platform_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_twitch_eventsub_platform_id ON public.twitch_eventsub_subscription USING btree (platform_id);


--
-- Name: idx_twitch_eventsub_streamer_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_twitch_eventsub_streamer_id ON public.twitch_eventsub_subscription USING btree (streamer_id);


--
-- Name: authenticated_users authenticated_users_streamer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authenticated_users
    ADD CONSTRAINT authenticated_users_streamer_id_fkey FOREIGN KEY (streamer_id) REFERENCES public.streamer(id) ON DELETE CASCADE;


--
-- Name: raffle_items raffle_items_streamer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.raffle_items
    ADD CONSTRAINT raffle_items_streamer_id_fkey FOREIGN KEY (streamer_id) REFERENCES public.streamer(id) ON DELETE CASCADE;


--
-- Name: streamer_platform streamer_platform_streamer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.streamer_platform
    ADD CONSTRAINT streamer_platform_streamer_id_fkey FOREIGN KEY (streamer_id) REFERENCES public.streamer(id) ON DELETE CASCADE;


--
-- Name: twitch_eventsub_subscription twitch_eventsub_subscription_streamer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.twitch_eventsub_subscription
    ADD CONSTRAINT twitch_eventsub_subscription_streamer_id_fkey FOREIGN KEY (streamer_id) REFERENCES public.streamer(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--


