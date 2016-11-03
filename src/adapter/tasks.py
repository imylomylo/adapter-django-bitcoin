import requests
from celery import shared_task

import logging

from decimal import Decimal
from django.conf import settings

from .utils import from_cents, to_cents
from .models import ReceiveTransaction, SendTransaction, UserAccount

from .exceptions import PlatformRequestFailedError

logger = logging.getLogger('django')

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

        if r.status_code in (200,201):
            tx.rehive_response = r.json()
            tx.status = 'Complete'
            tx.save()
        else:
            logger.info(headers)
            logger.info('Failed transaction update request: HTTP %s Error: %s' % (r.status_code, r.text))
            tx.rehive_response = {'status': r.status_code, 'data': r.text}
            tx.status = 'Failed'
            tx.save()

    except (requests.exceptions.RequestException, requests.exceptions.MissingSchema) as e:
        try:
            logger.info('Retry transaction update request due to connection error.')
            self.retry(countdown=5 * 60, exc=PlatformRequestFailedError)
        except PlatformRequestFailedError:
            logger.info('Final transaction update request failure due to connection error.')


@shared_task(bind=True, name='adapter.create_or_confirm_rehive_receive.task', max_retries=24, default_retry_delay=60 * 60)
def create_or_confirm_rehive_receive(self, tx_id: int, confirm: bool=False):
    tx = ReceiveTransaction.objects.get(id=tx_id)
    # If transaction has not yet been created, create it:
    if not tx.rehive_code:
        url = getattr(settings, 'REHIVE_API_URL') + '/admins/transactions/receive/'
        headers = {'Authorization': 'Token ' + getattr(settings, 'REHIVE_API_TOKEN')}

        try:
            # Make request:
            r = requests.post(url,
                              json={'recipient': tx.user_account.rehive_id,
                                    'amount': to_cents(tx.amount, 8),
                                    'currency': tx.currency,
                                    'issuer': tx.issuer,
                                    'metadata': tx.metadata,
                                    'from_reference': tx.external_id},
                              headers=headers)

            if r.status_code in (200, 201):
                tx.rehive_response = r.json()
                tx.rehive_code = tx.rehive_response['data']['tx_code']
                tx.status = 'Pending'
                tx.save()
            else:
                logger.info(headers)
                logger.info('Failed transaction update request: HTTP %s Error: %s' % (r.status_code, r.text))
                tx.status = 'Failed'
                tx.rehive_response = {'status': r.status_code, 'data': r.text}
                tx.save()

        except (requests.exceptions.RequestException, requests.exceptions.MissingSchema) as e:
            try:
                logger.info('Retry transaction update request due to connection error.')
                self.retry(countdown=5 * 60, exc=PlatformRequestFailedError)
            except PlatformRequestFailedError:
                logger.info('Final transaction update request failure due to connection error.')

    # After creation, or if tx already exists, confirm it if necessary
    if confirm:
        logger.info('Transaction update request.')

        # Update URL
        url = getattr(settings, 'REHIVE_API_URL') + '/admins/transactions/update/'

        # Add Authorization headers
        headers = {'Authorization': 'Token ' + getattr(settings, 'REHIVE_API_TOKEN')}

        try:
            # Make request
            r = requests.post(url, json={'tx_code': tx.rehive_code, 'status': 'Confirmed'}, headers=headers)

            if r.status_code in (200, 201):
                tx.rehive_response = r.json()
                tx.status = 'Complete'
                tx.save()
            else:
                logger.info(headers)
                logger.info('Failed transaction update request: HTTP %s Error: %s' % (r.status_code, r.text))
                tx.rehive_response = {'status': r.status_code, 'data': r.text}
                tx.status = 'Failed'
                tx.save()

        except (requests.exceptions.RequestException, requests.exceptions.MissingSchema) as e:
            try:
                logger.info('Retry transaction update request due to connection error.')
                self.retry(countdown=5 * 60, exc=PlatformRequestFailedError)
            except PlatformRequestFailedError:
                logger.info('Final transaction update request failure due to connection error.')


@shared_task()
def process_webhook_receive(webhook_type, receive_id, data):
    logger.debug('Incoming: Blockcypher Unconfirmed: ID: %s', str(receive_id))
    user_account = UserAccount.objects.get(id=receive_id)

    if webhook_type == 'confirmations':
        logger.info('Confirmations webhook')
        logger.info('Transaction: %s' % data['hash'])
        # TODO: Check if this is 'malleability' proof:
        if data['confirmations'] == 0:
            logger.info('Zero Confirmations')
            # Loop through outputs to count amount received:
            amount_received = Decimal('0')
            for o in data['outputs']:
                output_addresses = tuple(o['addresses'])

                # Bitcoin outputs usually have one address, but the API returns a tuple
                if len(output_addresses) > 1:
                    raise Exception('Bitcoin output has multiple addresses')

                for address in output_addresses:
                    if address == user_account.account_id:
                        output_value = from_cents(o['value'], 8)
                        amount_received += output_value

            tx = ReceiveTransaction.objects.create(user_account=user_account,
                                                   amount=amount_received,
                                                   external_id=data['hash'],
                                                   data=data,
                                                   status='Pending')

            tx.upload_to_rehive()

        elif data['confirmations'] >= 1:  # TODO: Make this customizable
            logger.info('More than 1 confirmation')
            tx = ReceiveTransaction.objects.get(external_id=data['hash'])
            if tx.status not in ('Confirmed', 'Complete', 'Failed'):
                logger.info('Confirming transaction')
                tx.data = data
                tx.status = 'Confirmed'
                tx.save()
                tx.upload_to_rehive()

    elif webhook_type == 'confidence':
        logger.info('Confidence webhook')
        if data['confidence'] > 0.9:  # TODO: Make this customizable
            logger.info('Greater than 90% confidence')
            #  TODO: Check if this is 'malleability' proof:
            tx = ReceiveTransaction.objects.get(external_id=data['hash'])
            if tx.status not in ('Confirmed', 'Complete', 'Failed'):
                logger.info('Confirming transaction')
                tx.data = data
                tx.status = 'Confirmed'
                tx.save()
                tx.upload_to_rehive()
