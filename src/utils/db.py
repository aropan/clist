#!/usr/bin/env python3


from django.apps import apps


def dictfetchall(cursor):
    "Return all rows from a cursor as a dict"
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def dictfetchone(cursor):
    """Return one row from a cursor as a dict"""
    columns = [col[0] for col in cursor.description]
    row = cursor.fetchone()
    return dict(zip(columns, row))


def find_app_by_table(table_name):
    # First, try to find a model with a direct mapping to the table name
    for model in apps.get_models():
        if model._meta.db_table == table_name:
            return model._meta.app_label

    # If no direct model found, check if the table is an automatic through table
    for model in apps.get_models():
        for field in model._meta.many_to_many:
            if field.remote_field.through._meta.db_table == table_name:
                return model._meta.app_label

    # If still not found, return None
    return None
