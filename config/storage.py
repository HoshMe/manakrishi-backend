from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


class R2Storage(S3Boto3Storage):
    """Cloudflare R2 storage — credentials set as class attrs to bypass django-storages settings lookup."""

    @property
    def endpoint_url(self):
        return settings.R2_ENDPOINT_URL

    @property
    def access_key(self):
        return settings.R2_ACCESS_KEY_ID

    @property
    def secret_key(self):
        return settings.R2_SECRET_ACCESS_KEY

    @property
    def bucket_name(self):
        return settings.R2_BUCKET_NAME

    @property
    def custom_domain(self):
        return settings.R2_PUBLIC_URL.replace('https://', '')

    region_name = 'auto'
    signature_version = 's3v4'
    default_acl = None
    querystring_auth = False
    object_parameters = {'CacheControl': 'max-age=86400'}
    file_overwrite = True
