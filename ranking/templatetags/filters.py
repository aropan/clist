import json

from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key, None) if dictionary else None

@register.filter
def json_loads(string):
    return json.loads(string) if isinstance(string, str) else None

@register.filter
def iteritems(dictionary):
    return sorted(dictionary.items()) if isinstance(dictionary, dict) else None

@register.filter
def multiply(value, arg):
    return value * arg

@register.filter
def addition(value, arg):
    return value + arg
