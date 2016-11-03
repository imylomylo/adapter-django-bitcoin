from datetime import timedelta
import os

CELERY_IMPORTS = ("adapter.models",)

CELERY_ENABLE_UTC = True
CELERY_TIMEZONE = "UTC"

CELERY_CREATE_MISSING_QUEUES = True
CELERY_PREFETCH_MULTIPLIER = 1

HOST_NAME = os.environ.get('HOST_NAME', 'local')

default_queue = '-'.join(('general-adapter', HOST_NAME))
CELERY_DEFAULT_QUEUE = default_queue

webhooks_queue = '-'.join(('webhooks', HOST_NAME))
CELERY_ROUTES = {'adapter.tasks.process_webhook_receive': {'queue': webhooks_queue}, }

BROKER_TRANSPORT = 'sqs'
BROKER_TRANSPORT_OPTIONS = {
    'region': 'eu-west-1',
    'visibility_timeout': 43200,
    'polling_interval': 1,
}

CELERYBEAT_SCHEDULE = {
    'check_stellar_receive': {
        'task': 'stellar_adapter.tasks.process_receive',
        'schedule': timedelta(seconds=1),
        'args': ()
    },
}

