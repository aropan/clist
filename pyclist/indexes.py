from django.contrib.postgres.indexes import GistIndex


class GistIndexTrgrmOps(GistIndex):
    def create_sql(self, model, schema_editor):
        # - this Statement is instantiated by the _create_index_sql()
        #   method of django.db.backends.base.schema.BaseDatabaseSchemaEditor.
        #   using sql_create_index template from
        #   django.db.backends.postgresql.schema.DatabaseSchemaEditor
        # - the template has original value:
        #   "CREATE INDEX %(name)s ON %(table)s%(using)s (%(columns)s)%(extra)s"
        statement = super().create_sql(model, schema_editor)
        # - however, we want to use a GIST index to accelerate trigram
        #   matching, so we want to add the gist_trgm_ops index operator
        #   class
        # - so we replace the template with:
        #   "CREATE INDEX %(name)s ON %(table)s%(using)s (%(columns)s gist_trgrm_ops)%(extra)s"
        statement.template = "CREATE INDEX %(name)s ON %(table)s%(using)s (%(columns)s gist_trgm_ops)%(extra)s"

        return statement
