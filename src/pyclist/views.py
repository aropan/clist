
from django.apps import apps
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import F
from el_pagination.decorators import page_templates

from clist.templatetags.extras import is_yes, timestamp_to_datetime
from pyclist.decorators import context_pagination
from utils.chart import make_chart


def create_field_to_select(**kwargs):
    ret = {
        'noajax': True,
        'nogroupby': True,
        'nourl': True,
        'nomultiply': True,
        'ajax_query': 'charts-field-select',
        'ajax_params': ['source'],
        'icon': False,
    }
    if kwargs.pop('multiply', False):
        ret.pop('nomultiply')
    if kwargs.pop('ajax', False):
        ret.pop('noajax')
    if kwargs.pop('groupby', False):
        ret.pop('nogroupby')
    ret.update(kwargs)
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
    significant_fields.extend(request.GET.getlist('selection'))
    for field in significant_fields[::-1]:
        if field in fields:
            fields.remove(field)
            fields.insert(0, field)

    x_field_select = create_field_to_select(options=fields)
    selection_field_select = create_field_to_select(options=fields, multiply=True)
    sort_field_select = create_field_to_select(options=fields, rev_order=True)

    selection_field_selects = []
    selections = request.get_filtered_list('selection', selection_field_select['options'])
    for selection in selections:
        field_type = models[source]['fields'][selection]['type']
        if field_type in {'GenericForeignKey'}:
            continue
        values = request.get_filtered_list(selection)
        field_select = create_field_to_select(values=values, name=selection,
                                              multiply=True, ajax=True, groupby=True)
        selection_field_selects.append(field_select)

    for selection in selection_field_selects:
        field = selection['name']
        values = selection['values']
        field_type = models[source]['fields'][field]['type']
        if field_type == 'BooleanField':
            values = [is_yes(v) for v in values]
        if values:
            entities = entities.filter(**{f'{field}__in': values})

    x_axis = request.get_filtered_value('x_axis', x_field_select['options'])
    if x_axis:
        x_from = request.get_filtered_value('x_from')
        x_to = request.get_filtered_value('x_to')
        if x_from and x_to:
            x_from = float(x_from)
            x_to = float(x_to)
            field_type = models[source]['fields'][x_axis]['type']
            if field_type in {'DateField', 'DateTimeField'}:
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
        groupby = request.get_filtered_value('groupby', fields)
        chart = make_chart(entities, x_axis, groupby=groupby)
        chart['name'] = 'x'
        if 'x_from' in chart and 'x_to' in chart:
            chart['range_selection'] = {
                'x_slider_id': 'x-range',
                'x_from': chart['x_from'],
                'x_to': chart['x_to'],
            }

    context.update({
        'x_field_select': x_field_select,
        'sort_field_select': sort_field_select,
        'selection_field_select': selection_field_select,
        'selection_field_selects': selection_field_selects,
        'per_page': 10,
        'per_page_more': 50,
        'entities': entities,
        'fields': fields,
        'chart': chart,
        'groupby': groupby,
        'x_axis': x_axis,
    })
    return context


@staff_member_required
@page_templates((
    ('charts_paging.html', 'entities_paging'),
))
@context_pagination()
def charts(request, template='charts.html'):
    models = {}
    app_models = apps.get_models()
    for model in app_models:
        app_label = model._meta.app_label
        model_name = model.__name__
        source = f'{app_label}.{model_name}'

        model_fields = models.setdefault(source, {
            'name': source,
            'model': model,
            'fields': {},
        })
        for field in model._meta.get_fields():
            model_fields['fields'][field.name] = {
                'name': field.name,
                'type': type(field).__name__,
            }

    source = request.get_filtered_value('source', models)
    source_field_select = create_field_to_select(options=models.keys())

    context = {
        'source': source,
        'models': models,
        'model': models[source] if source else None,
        'source_field_select': source_field_select,
    }

    update_context_by_source(request, context)

    return template, context
