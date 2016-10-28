import requests
from celery import shared_task

import logging

from decimal import Decimal
from django.conf import settings

from src.adapter.utils import from_cents
from .models import AdminAccount, ReceiveTransaction, SendTransaction, UserAccount

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


@shared_task()
def webhook_blockcypher_receive(webhook_type, receive_id, data):
    logger.debug('Incoming: Blockcypher Unconfirmed: ID: %s', str(receive_id))
    user_account = UserAccount.objects.get(id=receive_id)
    if webhook_type == 'unconfirmed':
        # Loop through outputs to count amount received:
        amount_received = Decimal('0')
        for o in data['outputs']:
            output_addresses = tuple(o['addresses'])

            # TODO: Check why this is an array and not a single address:
            # Bitcoin outputs usually have one address.
            if len(output_addresses) > 1:
                raise Exception('Bitcoin output has multiple addresses')

            for address in output_addresses:
                if address == user_account.account_id:
                    output_value = from_cents(o['value'], 8)
                    amount_received += output_value

        ReceiveTransaction.objects.create(user=user_account,
                                          amount=amount_received,
                                          external_id=data['hash'],
                                          data=data)




@shared_task()
def process_confidence(receive_id, data):
        logger.debug('Incoming: Blockcypher Confidence: ID: %s', str(receive_id))
        bitcoin_receive = BitcoinReceive.objects.get(id=receive_id)
        tx_hash = data['hash']
        bitcoin_transaction = BitcoinTransaction.objects.get_or_create(hash=tx_hash)[0]
        bitcoin_transaction.block_height = data['block_height']
        bitcoin_transaction.block_index = data['block_index']
        bitcoin_transaction.total = Decimal(data['total']) * Decimal('1e-8')
        bitcoin_transaction.fees = Decimal(data['fees']) * Decimal('1e-8')
        bitcoin_transaction.size = data['size']
        bitcoin_transaction.preference = data['preference']
        bitcoin_transaction.relayed_by = data['relayed_by']
        bitcoin_transaction.received = data['received']
        bitcoin_transaction.ver = data['ver']
        bitcoin_transaction.lock_time = data['lock_time']
        bitcoin_transaction.double_spend = data['double_spend'] in ['true', 'True', True]
        bitcoin_transaction.vin_sz = data['vin_sz']
        bitcoin_transaction.vout_sz = data['vout_sz']
        bitcoin_transaction.confirmations = data['confirmations']
        bitcoin_transaction.confidence = data['confidence']
        bitcoin_transaction.save()

        bitcoin_receive.amount_confident += amount_received
        if bitcoin_receive.amount_confident + bitcoin_receive.amount_confirmed >= bitcoin_receive.amount_required:
            if bitcoin_receive.wallet_transaction.status != 'Confirmed':
                bitcoin_receive.status = 'Confident'
                bitcoin_receive.wallet_transaction.confirm_transaction()

        bitcoin_receive.save()


@shared_task()
def process_confirmations(receive_id, data):
        logger.debug('Incoming: Blockcypher Confirmations: ID: %s', str(receive_id))

        bitcoin_receive = BitcoinReceive.objects.get(id=receive_id)

        tx_hash = data['hash']
        bitcoin_transaction = BitcoinTransaction.objects.get_or_create(hash=tx_hash)[0]
        bitcoin_transaction.block_height = data['block_height']
        bitcoin_transaction.block_index = data['block_index']
        bitcoin_transaction.total = Decimal(data['total']) * Decimal('1e-8')
        bitcoin_transaction.fees = Decimal(data['fees']) * Decimal('1e-8')
        bitcoin_transaction.size = data['size']
        bitcoin_transaction.preference = data['preference']
        bitcoin_transaction.relayed_by = data['relayed_by']
        bitcoin_transaction.received = data['received']
        bitcoin_transaction.ver = data['ver']
        bitcoin_transaction.lock_time = data['lock_time']
        bitcoin_transaction.double_spend = data['double_spend'] in ['true', 'True', True]
        bitcoin_transaction.vin_sz = data['vin_sz']
        bitcoin_transaction.vout_sz = data['vout_sz']
        bitcoin_transaction.confirmations = data['confirmations']
        bitcoin_transaction.confidence = data['confidence']
        bitcoin_transaction.save()

        # Save inputs:
        print(data)
        print(data['inputs'])
        for i in data['inputs']:
            print(i)
            inpt = BitcoinInput.objects.create(transaction=bitcoin_transaction)
            inpt.prev_hash = i['prev_hash']
            inpt.output_index = i['output_index']
            inpt.script = i['script']
            inpt.output_value = Decimal(i['output_value']) * Decimal('1e-8')
            inpt.sequence = i['sequence']
            inpt.script_type = i['script_type']
            inpt.save()

            input_addresses = tuple(i['addresses'])
            for address in input_addresses:
                address_obj = Address.objects.get_or_create(address=address)[0]
                address_obj.input.add(inpt)
                address_obj.transaction.add(bitcoin_transaction)
                address_obj.save()

        # Save outputs:
        amount_received = Decimal('0')
        for o in data['outputs']:
            outpt = BitcoinOutput.objects.create(transaction=bitcoin_transaction)
            outpt.script = o['script']
            outpt.value = Decimal(o['value']) * Decimal('1e-8')
            outpt.script_type = o['script_type']
            outpt.save()

            output_addresses = tuple(o['addresses'])

            # TODO: Check why this is an array and not a single address:
            for address in output_addresses:
                if address == bitcoin_receive.address:
                    amount_received += outpt.value

                address_obj = Address.objects.get_or_create(address=address)[0]
                address_obj.output.add(outpt)
                address_obj.transaction.add(bitcoin_transaction)
                address_obj.save()

            if len(output_addresses) > 1:
                raise Exception('Bitcoin output has multiple addresses')

        bitcoin_receive.amount_confirmed += amount_received
        if bitcoin_receive.amount_confident + bitcoin_receive.amount_confirmed >= bitcoin_receive.amount_required:
            if bitcoin_receive.wallet_transaction.status != 'Confirmed':
                bitcoin_receive.status = 'Confirmed'
                bitcoin_receive.wallet_transaction.confirm_transaction()

        bitcoin_receive.save()
