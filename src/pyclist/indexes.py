from django.contrib.postgres.indexes import GistIndex
from django.db import models
from django.db.backends.utils import names_digest, split_identifier

GIST_INDEX_TRGRM_OPS_SEP = ' || '


class GistIndexTrgrmOps(GistIndex):
    def create_sql(self, *args, **kwargs):
        # - this Statement is instantiated by the _create_index_sql()
        #   method of django.db.backends.base.schema.BaseDatabaseSchemaEditor.
        #   using sql_create_index template from
        #   django.db.backends.postgresql.schema.DatabaseSchemaEditor
        # - the template has original value:
        #   "CREATE INDEX %(name)s ON %(table)s%(using)s (%(columns)s)%(extra)s"
        statement = super().create_sql(*args, **kwargs)
        # - however, we want to use a GIST index to accelerate trigram
        #   matching, so we want to add the gist_trgm_ops index operator
        #   class
        # - so we replace the template with:
        #   "CREATE INDEX %(name)s ON %(table)s%(using)s (%(columns)s gist_trgrm_ops)%(extra)s"
        columns = statement.parts['columns'].columns
        if len(columns) > 1:
            sep = f" || '{GIST_INDEX_TRGRM_OPS_SEP}' || "
            columns = sep.join(statement.parts['columns'].columns)
            statement.parts['columns'] = f'({columns})'
        statement.template = "CREATE INDEX %(name)s ON %(table)s%(using)s (%(columns)s gist_trgm_ops)%(extra)s"

        return statement


class ExpressionIndex(models.Index):
    def __init__(self, *_, expressions=(), name=None, db_tablespace=None, opclasses=(), condition=None):
        super().__init__(fields=[str(e) for e in expressions],
                         name=name,
                         db_tablespace=db_tablespace,
                         opclasses=opclasses,
                         condition=condition)
        self.expressions = expressions

    def deconstruct(self):
        path, args, kwargs = super().deconstruct()
        kwargs.pop('fields')
        kwargs['expressions'] = self.expressions
        return path, args, kwargs

    def set_name_with_model(self, model):
        self.fields_orders = [(model._meta.pk.name, '')]
        _, table_name = split_identifier(model._meta.db_table)
        digest = names_digest(table_name, *self.fields, length=6)
        self.name = f"{table_name[:19]}_{digest}_{self.suffix}"

    def create_sql(self, model, schema_editor, using='', **kwargs):
        class Descriptor:
            db_tablespace = ''

            def __init__(self, expression):
                self.column = str(expression)

        col_suffixes = [''] * len(self.expressions)
        condition = self._get_condition_sql(model, schema_editor)
        statement = schema_editor._create_index_sql(
            model,
            fields=[Descriptor(e) for e in self.expressions],
            name=self.name,
            using=using,
            db_tablespace=self.db_tablespace,
            col_suffixes=col_suffixes,
            opclasses=self.opclasses,
            condition=condition,
            **kwargs,
        )

        compiler = model._meta.default_manager.all().query.get_compiler(connection=schema_editor.connection)
        statement.parts['columns'] = ", ".join(
            "({})".format(self.compile_expression(e, compiler))
            for e in self.expressions
        )
        return statement

    def compile_expression(self, expression, compiler):
        query = compiler.query
        expression = expression.resolve_expression(query, allow_joins=False)
        sql, params = expression.as_sql(compiler, compiler.connection)
        return sql % params


class DescNullsLastIndex(models.Index):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields_orders = [
            (field, 'DESC NULLS LAST' if order == 'DESC' else order)
            for field, order in self.fields_orders
        ]
