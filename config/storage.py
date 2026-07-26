from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


class R2Storage(S3Boto3Storage):
    """Cloudflare R2 storage backend."""

    def __init__(self, **kwargs):
        kwargs.setdefault('endpoint_url', settings.R2_ENDPOINT_URL)
        kwargs.setdefault('access_key', settings.R2_ACCESS_KEY_ID)
        kwargs.setdefault('secret_key', settings.R2_SECRET_ACCESS_KEY)
        kwargs.setdefault('bucket_name', settings.R2_BUCKET_NAME)
        kwargs.setdefault('custom_domain', settings.R2_PUBLIC_URL.replace('https://', ''))
        kwargs.setdefault('region_name', 'auto')
        kwargs.setdefault('signature_version', 's3v4')
        kwargs.setdefault('default_acl', None)
        kwargs.setdefault('querystring_auth', False)
        kwargs.setdefault('file_overwrite', True)
        super().__init__(**kwargs)
