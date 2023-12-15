from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from pyclist.middleware import RedirectException
from true_coders.models import CoderList


def add_query_to_list(request, uuid, query):
    if not request.user.is_authenticated or not uuid or not query:
        return
    coder = request.user.coder
    get_object_or_404(CoderList, owner=coder, uuid=uuid)
    url = reverse('coder:list', args=(uuid,))
    request.session['view_list_request_post'] = {'raw': query, 'uuid': uuid}
    raise RedirectException(redirect(url))
