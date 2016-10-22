import requests
from celery import shared_task

import logging

from django.conf import settings
from .models import AdminAccount, ReceiveTransaction, SendTransaction

from .exceptions import PlatformRequestFailedError

logger = logging.getLogger('django')


@shared_task
def process_receive():
    logger.info('checking stellar receive transactions...')
    hotwallet = AdminAccount.objects.get(name='hotwallet')
    hotwallet.process_new_transactions()


@shared_task
def default_task():
    logger.info('running default task')
    return 'True'


@shared_task(bind=True, name='adapter.confirm_rehive_tx.task', max_retries=24, default_retry_delay=60 * 60)
def confirm_rehive_transaction(self, tx_id: int, tx_type: str):
    if tx_type == 'receive':
        tx = ReceiveTransaction.objects.get(id=tx_id)
    elif tx_type == 'send':
        tx = SendTransaction.objects.get(id=tx_id)
    else:
        raise TypeError('Invalid transaction type specified.')

    logger.info('Transaction update request.')

    # Update URL
    url = getattr(settings, 'REHIVE_API_URL') + '/admins/transactions/update/'

    # Add Authorization headers
    headers = {'Authorization': 'Token ' + getattr(settings, 'REHIVE_API_TOKEN')}

    try:
        # Make request
        r = requests.post(url, json={'tx_code': tx.rehive_code, 'status': 'Confirmed'}, headers=headers)

        if r.status_code == 200:
            tx.rehive_response = r.json()
        else:
            logger.info(headers)
            logger.info('Failed transaction update request: HTTP %s Error: %s' % (r.status_code, r.text))
            tx.rehive_response = {'status': r.status_code, 'data': r.text}

    except (requests.exceptions.RequestException, requests.exceptions.MissingSchema) as e:
        try:
            logger.info('Retry transaction update request due to connection error.')
            self.retry(countdown=5 * 60, exc=PlatformRequestFailedError)
        except PlatformRequestFailedError:
            logger.info('Final transaction update request failure due to connection error.')


@shared_task(bind=True, name='adapter.create_rehive_receive.task', max_retries=24, default_retry_delay=60 * 60)
def create_rehive_receive(self, tx_id: int):
    tx = ReceiveTransaction.objects.get(id=tx_id)
    url = getattr(settings, 'REHIVE_API_URL') + '/admins/transactions/receive/'
    headers = {'Authorization': 'Token ' + getattr(settings, 'REHIVE_API_TOKEN')}

    try:
        # Make request:
        r = requests.post(url,
                          json={'recipient': tx.recipient,
                                'amount': tx.amount,
                                'currency': tx.currency,
                                'issuer': tx.issuer,
                                'metadata': tx.metadata},
                          headers=headers)

        if r.status_code == 200:
            tx.rehive_response = r.json()
            tx.status = 'Pending'
            tx.save()
        else:
            logger.info(headers)
            logger.info('Failed transaction update request: HTTP %s Error: %s' % (r.status_code, r.text))
            tx.status = 'Failed'
            tx.rehive_response = {'status': r.status_code, 'data': r.text}

    except (requests.exceptions.RequestException, requests.exceptions.MissingSchema) as e:
        try:
            logger.info('Retry transaction update request due to connection error.')
            self.retry(countdown=5 * 60, exc=PlatformRequestFailedError)
        except PlatformRequestFailedError:
            logger.info('Final transaction update request failure due to connection error.')



