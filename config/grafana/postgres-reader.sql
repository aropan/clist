-- Run after creating grafana_reader:
-- docker compose exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < config/grafana/postgres-reader.sql
\set ON_ERROR_STOP on

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM grafana_reader;

GRANT SELECT (created, modified) ON public.clist_resource TO grafana_reader;
GRANT SELECT (updated) ON public.clist_contest TO grafana_reader;
GRANT SELECT (created, modified) ON public.clist_problem TO grafana_reader;
GRANT SELECT (created, name, status, elapsed, environment) ON public.logify_eventlog TO grafana_reader;
GRANT SELECT (created) ON public.ranking_account TO grafana_reader;
GRANT SELECT (created) ON public.ranking_statistics TO grafana_reader;
GRANT SELECT (created, modified) ON public.true_coders_coder TO grafana_reader;
