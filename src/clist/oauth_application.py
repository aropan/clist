from functools import wraps
from urllib.parse import urlsplit

from django.core import checks
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.db.models.signals import pre_save
from django.utils.translation import gettext_lazy as _
from oauth2_provider.models import get_application_model

LOOPBACK_HTTP_HOSTS = frozenset(("localhost", "127.0.0.1", "::1"))
REDIRECT_URI_FIELDS = ("redirect_uris", "post_logout_redirect_uris")


def get_non_loopback_http_redirect_uris(value):
    invalid_uris = []
    for uri in value.split():
        try:
            parsed_uri = urlsplit(uri)
        except ValueError:
            if uri.lower().startswith("http:"):
                invalid_uris.append(uri)
            continue
        if parsed_uri.scheme == "http" and parsed_uri.hostname not in LOOPBACK_HTTP_HOSTS:
            invalid_uris.append(uri)
    return invalid_uris


def get_oauth_application_redirect_uri_violations(application):
    return {
        field_name: invalid_uris
        for field_name in REDIRECT_URI_FIELDS
        if (invalid_uris := get_non_loopback_http_redirect_uris(getattr(application, field_name)))
    }


def validate_oauth_application_redirect_uris(application):
    violations = get_oauth_application_redirect_uri_violations(application)
    if not violations:
        return

    raise ValidationError({
        field_name: ValidationError(
            _(
                "HTTP redirect URIs are allowed only for localhost, 127.0.0.1, or ::1; "
                "use HTTPS for every other host: %(uris)s"
            ),
            code="non_loopback_http_redirect_uri",
            params={"uris": ", ".join(invalid_uris)},
        )
        for field_name, invalid_uris in violations.items()
    })


def _validate_oauth_application_before_save(sender, instance, raw=False, **kwargs):
    if not raw:
        validate_oauth_application_redirect_uris(instance)


def install_oauth_application_validation():
    """Attach host-aware validation to OAuth Toolkit's third-party model."""
    application_model = get_application_model()
    if not getattr(application_model, "_clist_redirect_uri_validation_installed", False):
        original_clean = application_model.clean

        @wraps(original_clean)
        def clean(application):
            original_clean(application)
            validate_oauth_application_redirect_uris(application)

        application_model.clean = clean
        application_model._clist_redirect_uri_validation_installed = True

    # Model forms call clean(); the signal also protects direct model saves.
    pre_save.connect(
        _validate_oauth_application_before_save,
        sender=application_model,
        dispatch_uid="clist.validate_oauth_application_redirect_uris",
        weak=False,
    )


@checks.register(checks.Tags.security, deploy=True)
def check_oauth_application_redirect_uris(app_configs, **kwargs):
    application_model = get_application_model()
    errors = []
    try:
        applications = application_model.objects.only("pk", *REDIRECT_URI_FIELDS).iterator()
        for application in applications:
            for field_name, invalid_uris in get_oauth_application_redirect_uri_violations(application).items():
                errors.append(
                    checks.Error(
                        f"OAuth application {application.pk} has non-loopback HTTP URIs in {field_name}: "
                        f"{', '.join(invalid_uris)}",
                        hint="Use HTTPS, or a loopback URI with localhost, 127.0.0.1, or ::1.",
                        obj=application,
                        id="clist.E001",
                    )
                )
    except DatabaseError:
        errors.append(
            checks.Error(
                "OAuth application redirect URIs could not be audited.",
                hint="Ensure the database is available and all OAuth Toolkit migrations are applied.",
                id="clist.E002",
            )
        )
    return errors
