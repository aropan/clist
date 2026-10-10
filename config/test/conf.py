# Synthetic configuration for the isolated test stack (docker-compose.test.yml).
# Every value is fake: hosts use the reserved .invalid TLD and nothing here is a real credential.

ADMINS = (("CLIST Test", "admin@clist.invalid"),)

EMAIL_HOST = "smtp.invalid"
EMAIL_HOST_USER = "noreply@clist.invalid"
EMAIL_HOST_PASSWORD = "synthetic-test-password"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
STOP_EMAIL = True

SECRET_KEY = "synthetic-test-secret-key-for-isolated-ci-runs-only-0123456789"
TELEGRAM_TOKEN = "123456:synthetic-test-token"
TELEGRAM_NAME = "ClistTestBot"
TELEGRAM_ADMIN_CHAT_ID = "0"

WEBPUSH_SETTINGS = {
    "VAPID_PUBLIC_KEY": "synthetic-test-vapid-public-key",
    "VAPID_PRIVATE_KEY": "synthetic-test-vapid-private-key",
    "VAPID_ADMIN_EMAIL": "admin@clist.invalid",
}

GEOIP_ACCOUNT_ID = ""
GEOIP_LICENSE_KEY = ""

CUSTOM_COUNTRIES = {}
FILTER_CUSTOM_COUNTRIES = {}
