from pprint import pprint

from django.http import JsonResponse


def test(request):
    print('GET:')
    pprint(request.GET)
    print('POST:')
    pprint(request.POST)
    return JsonResponse({'status': 'ok'})
