# CLIST's Django session cookie is domain-wide (.clist.by) and also named
# "sessionid"; use a distinct name so the two don't clash on this subdomain
# (a clashing cookie breaks the nginx auth_request gate with a redirect loop).
SESSION_COOKIE_NAME = 'hc_sessionid'
