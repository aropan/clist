#!/usr/bin/env python3

from django.db import models, transaction
from django.db.models.signals import post_delete, post_init, post_save


def get_m2m_field_for_through(instance, sender):
    for field in instance._meta.get_fields():
        if isinstance(field, models.ManyToManyRel):
            if field.through == sender:
                return field
        elif field.is_relation and field.many_to_many:
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


def update_foreign_key_n_field_on_change(instance, signal, attr, field, **kwargs):
    attr_id = f'{attr}_id'
    model = instance._meta.get_field(attr).related_model
    if signal == post_init:
        setattr(instance, f'_{attr_id}', getattr(instance, attr_id))
    elif signal == post_save:
        _value, value = getattr(instance, f'_{attr_id}', None), getattr(instance, attr_id)
        if kwargs.get('created'):
            _value = None
        if _value == value:
            return
        with transaction.atomic():
            if _value:
                model.objects.filter(pk=_value).update(**{field: models.F(field) - 1})
            if value:
                model.objects.filter(pk=value).update(**{field: models.F(field) + 1})
    elif signal == post_delete:
        value = getattr(instance, f'_{attr_id}', None) or getattr(instance, attr_id)
        if value:
            model.objects.filter(pk=value).update(**{field: models.F(field) - 1})
