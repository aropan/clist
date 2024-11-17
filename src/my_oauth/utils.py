#!/usr/bin/env python3

import json
from urllib.parse import parse_qsl

import requests
from django.forms.models import model_to_dict


def access_token_from_response(response):
    if response.status_code != requests.codes.ok:
        raise Exception('Response status code not equal ok.')
    try:
        access_token = json.loads(response.text)
    except Exception:
        access_token = dict(parse_qsl(response.text))
    return access_token


def refresh_acccess_token(token):
    service = token.service
    args = model_to_dict(service)
    args.update(token.access_token)
    refresh_token_uri = service.refresh_token_uri % args
    refresh_token_post = json.loads(service.refresh_token_post % args)
    response = requests.post(refresh_token_uri, data=refresh_token_post)
    access_token = access_token_from_response(response)
    return access_token
