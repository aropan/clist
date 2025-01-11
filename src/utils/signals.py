#!/usr/bin/env python3

from django.db import models


def get_m2m_field_for_through(instance, sender):
    for field in instance._meta.get_fields():
        if field.is_relation and field.many_to_many:
            if field.remote_field.through == sender:
                return field
    raise ValueError('No ManyToManyField for through model')


def update_n_field_on_change(sender, instance, action, reverse, pk_set, model, field, **kwargs):
    ADD_ACTION = 'post_add'
    REMOVE_ACTION = 'pre_remove'
    CLEAR_ACTION = 'pre_clear'
    if action == ADD_ACTION or action == REMOVE_ACTION:
        delta = len(pk_set) if reverse else 1
        delta = -delta if action == REMOVE_ACTION else delta
    elif action == CLEAR_ACTION:
        if reverse:
            delta = -getattr(instance, field)
        else:
            m2m_field = get_m2m_field_for_through(instance, sender)
            pk_set = getattr(instance, m2m_field.name).values_list('pk', flat=True)
            delta = -1
    else:
        return
    if reverse:
        setattr(instance, field, getattr(instance, field) + delta)
        instance.save(update_fields=[field])
    elif pk_set:
        if action == REMOVE_ACTION:
            m2m_field = get_m2m_field_for_through(instance, sender)
            qs = getattr(instance, m2m_field.name)
        else:
            qs = model.objects
        qs.filter(pk__in=pk_set).update(**{field: models.F(field) + delta})


def update_n_field_on_delete(objects, field):
    objects.update(**{field: models.F(field) - 1})
