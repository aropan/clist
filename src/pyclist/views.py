
import functools
import operator
from copy import deepcopy
from urllib.parse import urlparse

from django.apps import apps
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import F, Q
from django.http import HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.urls import NoReverseMatch, reverse
from django.utils.timezone import now
from el_pagination.decorators import page_templates

from clist.templatetags.extras import allowed_redirect, is_yes, timestamp_to_datetime, url_transform
from pyclist.decorators import context_pagination, extra_context_without_pagination
from utils.chart import make_chart
from utils.db import get_delete_info
from utils.timetools import parse_duration


def create_field_to_select(**kwargs):
    ret = {
        'noajax': True,
        'nogroupby': True,
        'nourl': True,
        'nomultiply': True,
        'ajax_query': 'charts-field-select',
        'ajax_params': ['source'], 'icon': False,
    }
    if kwargs.pop('multiply', False):
        ret.pop('nomultiply')
    if kwargs.pop('ajax', False):
        ret.pop('noajax')
    if kwargs.pop('groupby', False):
        ret.pop('nogroupby')
    ret.update(kwargs)
    if 'options' in ret:
        ret['options'] = deepcopy(ret['options'])
    return ret


def update_context_by_source(request, context):
    source = context['source']
    if not source:
        return

    fields = []
    entities = None
    x_field_select = None
    x_axis = None
    selection_field_select = None
    sort_field_select = None
    groupby = None
    chart = None

    models = context['models']
    entities = models[source]['model'].objects.all()
    entity_first = entities.first()

    fields = []
    for field, field_data in models[source]['fields'].items():
        field_type = field_data['type']
        if field_type.endswith('Rel') or field_type in ['ManyToManyField', 'GenericRelation']:
            continue
        if field in fields:
            continue
        # COMMENT: ranking.Accounts works long
        # if field_type == 'ForeignKey':
        #     entities = entities.select_related(field)
        fields.append(field)

    significant_fields = ['id']
    significant_fields.append(request.GET.get('x_axis'))
    significant_fields.append(request.GET.get('y_axis'))
    significant_fields.extend(request.GET.getlist('selection'))
    for field in significant_fields[::-1]:
        if field in fields:
            fields.remove(field)
            fields.insert(0, field)

    x_field_select = create_field_to_select(options=fields)
    x_axis = request.get_filtered_value('x_axis', x_field_select['options'])
    x_axis_field_type = models[source]['fields'][x_axis]['type'] if x_axis else None
    x_axis_date = x_axis_field_type in {'DateField', 'DateTimeField'}
    x_range_options = ['15 minutes', '1 hour', '6 hours', '1 day', '7 days', '30 days', '90 days', '365 days']
    x_range_select = create_field_to_select(field='x_range', options=x_range_options) if x_axis_date else None

    y_field_select = create_field_to_select(options=fields)
    y_axis = request.get_filtered_value('y_axis', y_field_select['options'])
    y_agg_select = create_field_to_select(options=['avg', 'sum', 'max', 'min', 'count', 'percentile'], noempty=True)
    y_agg = request.get_filtered_value('y_agg', y_agg_select['options'], default_first=True)
    percentile = float(request.get_filtered_value('percentile') or 0.5)
    selection_field_values = request.get_filtered_list('selection', options=list(fields))
    selection_field_select = create_field_to_select(options=fields, values=selection_field_values, multiply=True)
    sort_field_select = create_field_to_select(options=fields, rev_order=True)

    selection_field_selects = []
    selections = request.get_filtered_list('selection', selection_field_select['options'])
    for selection in selections:
        field_type = models[source]['fields'][selection]['type']
        if field_type in {'GenericForeignKey'}:
            continue
        values = request.get_filtered_list(selection)
        field_select = create_field_to_select(values=values, name=selection,
                                              multiply=True, ajax=True, groupby=bool(x_axis))
        selection_field_selects.append(field_select)

    for selection in selection_field_selects:
        field = selection['name']
        values = selection['values']
        field_type = models[source]['fields'][field]['type']
        if field_type == 'BooleanField':
            values = [is_yes(v) for v in values]
        if values:
            field_op = request.get_filtered_value(f'{field}_op', options=['eq', 'in'], default_first=True)
            if field_op == 'eq':
                entity_filter = Q(**{f'{field}__in': values})
            elif field_op == 'in':
                entity_filter = functools.reduce(operator.ior, (Q(**{f'{field}__contains': value}) for value in values))
            if 'None' in values:
                entity_filter |= Q(**{f'{field}__isnull': True})
            entities = entities.filter(entity_filter)

    if x_axis:
        x_from = request.get_filtered_value('x_from')
        x_to = request.get_filtered_value('x_to')
        if x_range_select:
            x_range = request.get_filtered_value(x_range_select['field'], x_range_select['options'])
            if x_range:
                x_to = now()
                x_from = x_to - parse_duration(x_range)
                x_to = x_to.timestamp()
                x_from = x_from.timestamp()
        if x_from and x_to:
            x_from = float(x_from)
            x_to = float(x_to)
            if x_axis_date:
                x_from = timestamp_to_datetime(x_from)
                x_to = timestamp_to_datetime(x_to)
            entities = entities.filter(**{f'{x_axis}__gte': x_from}, **{f'{x_axis}__lte': x_to})

    sort_field = request.get_filtered_value('sort', sort_field_select['options'])
    if sort_field:
        sort_order = request.get_filtered_value('sort_order', ['asc', 'desc'])
        order_by = getattr(F(sort_field), sort_order)(nulls_last=True)
    elif x_axis:
        order_by = F(x_axis).desc(nulls_last=True)
    else:
        order_by = None
    if order_by:
        entities = entities.order_by(order_by, 'id')

    if x_axis:
        groupby = request.get_filtered_value('groupby', fields, allow_empty=True)
        aggregations = {y_axis: {'op': y_agg, 'percentile': percentile}} if y_axis else None
        chart = make_chart(entities, x_axis, groupby=groupby, aggregations=aggregations)
        if chart:
            if aggregations:
                chart['y_value'] = y_axis
            chart['name'] = 'x'
            if 'x_from' in chart and 'x_to' in chart:
                chart['range_selection'] = {
                    'x_slider_id': 'x-range',
                    'x_from': chart['x_from'],
                    'x_to': chart['x_to'],
                }

    entity_fields = []
    if entity_first is not None:
        for field in dir(entity_first):
            if field.startswith('_') or field in entity_fields:
                continue
            if hasattr(getattr(entity_first, field, None), '__call__'):
                continue
            entity_fields.append(field)
    entity_fields_select = create_field_to_select(options=entity_fields, multiply=True)
    entity_fields = request.get_filtered_list('field', options=entity_fields_select['options'])
    for field in entity_fields[::-1]:
        if field in fields:
            fields.remove(field)
        fields.insert(1, field)

    context.update({
        'x_field_select': x_field_select,
        'x_range_select': x_range_select,
        'y_field_select': y_field_select,
        'y_agg_select': y_agg_select,
        'sort_field_select': sort_field_select,
        'selection_field_select': selection_field_select,
        'selection_field_selects': selection_field_selects,
        'entity_fields_select': entity_fields_select,
        'per_page': 25,
        'per_page_more': 50,
        'entities': entities,
        'fields': fields,
        'entity_fields': entity_fields,
        'chart': chart,
        'groupby': groupby,
        'x_axis': x_axis,
        'y_axis': y_axis,
        'y_agg': y_agg,
        'percentile': percentile,
    })
    return context


@staff_member_required
@page_templates((
    ('charts_paging.html', 'entities_paging'),
))
@extra_context_without_pagination('clist.view_full_table')
@context_pagination()
def charts(request, template='charts.html'):
    models = {}
    app_models = apps.get_models()
    for model in app_models:
        app_label = model._meta.app_label
        model_name = model.__name__
        source = f'{app_label}.{model_name}'
        try:
            admin_url = reverse('admin:%s_%s_changelist' % (app_label, model_name.lower()))
        except NoReverseMatch:
            admin_url = None

        model_fields = models.setdefault(source, {
            'name': source,
            'model': model,
            'admin_url': admin_url,
            'fields': {},
        })
        for field in model._meta.get_fields():
            model_fields['fields'][field.name] = {
                'name': field.name,
                'type': type(field).__name__,
            }

    source = request.get_filtered_value('source', models)
    source_field_select = create_field_to_select(options=list(models.keys()))

    context = {
        'source': source,
        'models': models,
        'model': models[source] if source else None,
        'source_field_select': source_field_select,
    }

    update_context_by_source(request, context)

    if action := request.GET.get('action'):
        if action == 'pre-delete':
            delete_info = get_delete_info(context['entities'])
            return JsonResponse({'status': 'ok', 'data': delete_info})
        elif action == 'delete':
            deleted_info = context['entities'].delete()
            request.logger.info(f'Deleted: {deleted_info}')
        return allowed_redirect(url_transform(request, action=None, with_remove=True))

    return template, context


@staff_member_required
def change_environment(request):
    referer_url = request.META.get('HTTP_REFERER')
    if not referer_url:
        return HttpResponseBadRequest('No referer')
    parse_result = urlparse(referer_url)
    domain = parse_result.netloc
    if domain not in settings.CHANING_HOSTS_:
        return HttpResponseBadRequest('Not allowed')
    index = settings.CHANING_HOSTS_.index(domain)
    index = (index + 1) % len(settings.CHANING_HOSTS_)
    new_domain = settings.CHANING_HOSTS_[index]
    new_url = parse_result._replace(netloc=new_domain).geturl()
    return HttpResponseRedirect(new_url)
