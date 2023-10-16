#!/usr/bin/env python3

from django.db.models import F, Window
from django.db.models.functions.window import RowNumber


def row_numbering(qs, pk, field='row_number'):
    qs = qs.annotate(**{field: Window(expression=RowNumber(), order_by=qs.query.order_by)})
    db_table = qs.model._meta.db_table
    field_pk = f'{db_table}_id'
    qs = qs.annotate(**{field_pk: F('id')})

    sql_query, sql_params = qs.query.sql_with_params()
    qs = qs.model.objects.raw(
        '''
        SELECT * FROM ({}) %s WHERE "%s" = %s
        '''.format(sql_query),
        [*sql_params, db_table, field_pk, pk],
    )
    return qs
