from django.apps import AppConfig


class ClistConfig(AppConfig):
    name = "clist"

    def ready(self):
        from clist.oauth_application import install_oauth_application_validation

        install_oauth_application_validation()
