from logging import getLogger

import requests
from django.conf import settings

from .utils import to_cents

logger = getLogger('django')
import bitcoin, blockcypher
from urllib.parse import urlparse, urlencode, urljoin
from django.contrib.sites.shortcuts import get_current_site


class AbstractBaseInteface:
    """
    Interface to handle all API calls to third-party account.
    """

    def __init__(self, account):
        # Always linked to an AdminAccount
        self.account = account

    def get_user_account_id(self):
        """
        Generated or retrieve an account ID from third-party API or cryptocurrency.
        """
        raise NotImplementedError('subclasses of AbstractBaseUser must provide a get_user_account_id() method')

    def get_user_account_details(self) -> dict:
        """
        Returns account id and details
        Should return dict of the form:
        {'account_id': ...
         'details': {...}
         }
        """
        raise NotImplementedError('subclasses of AbstractBaseUser must provide a get_user_account_id() method')

    def get_account_id(self):
        """
        Generated or retrieve an account ID from third-party API or cryptocurrency.
        """
        raise NotImplementedError('subclasses of AbstractBaseUser must provide a get_user_account_id() method')

    def get_account_details(self) -> dict:
        """
        Returns account id and details
        Should return dict of the form:
        {'account_id': ...
         'details': {...}
         }
        """
        raise NotImplementedError('subclasses of AbstractBaseUser must provide a get_account_id() method')


class Interface(AbstractBaseInteface):
    """
    Bitcoin Interface
    """
    def _get_private_key(self):
        """
        Get the private key associated with the admin account.
        """
        if self.account.secret.get('seed'):
            seed = self.account.secret.get('seed')
            index = self.account.secret.get('current_index', 0)  # last used primary index.
            privkey = bitcoin.electrum_privkey(seed, index, 0)
            return privkey
        else:
            raise NotImplementedError('Account does not have valid seed')

    def get_user_account_id(self):
        if self.account.secret.get('mpk'):
            mpk = self.account.secret.get('mpk')
            idx = self.account.secret.get('current_index')
            pubkey = bitcoin.electrum_pubkey(mpk, idx)
            address = bitcoin.pubtoaddr(pubkey)

            if 'current_index' in self.account.secret:
                self.account.secret['current_index'] += 1
            else:
                self.account.secret['current_index'] = 0

            self.account.save()
            return address
        else:
            raise NotImplementedError('Account does not have valid MPK')

    def get_account_id(self):
        # TODO: switch to compressed address
        privkey = self._get_private_key()
        pubkey = bitcoin.privkey_to_pubkey(privkey)
        address = bitcoin.pubtoaddr(pubkey)
        return address

    def send(self, tx):
        logger.info('Creating bitcoin send transaction...')

        to_satoshis = to_cents(tx.amount, 8)

        # Private Key, Public Key and Address
        from_privkey = self._get_private_key()
        from_pubkey = bitcoin.privkey_to_pubkey(from_privkey)
        from_address = self.get_account_id()
        change_address = from_address

        # Transaction inputs and outputs:
        inputs = [{'address': from_address}, ]
        outputs = [{'address': tx.recipient, 'value': to_satoshis}, ]
        logger.info('inputs: %s' % inputs)
        logger.info('outputs: %s' % outputs)

        # Unsigned Transaction:
        unsigned_tx = blockcypher.create_unsigned_tx(
            inputs=inputs,
            outputs=outputs,
            change_address=change_address,
            coin_symbol='btc',
            verify_tosigntx=False,  # will verify in next step
            include_tosigntx=True,
            api_key=settings.BLOCKCYPHER_TOKEN,
        )
        logger.info('unsigned_tx: %s' % unsigned_tx)

        # Verify Transaction
        tx_is_correct, err_msg = blockcypher.verify_unsigned_tx(
            unsigned_tx=unsigned_tx,
            inputs=inputs,
            outputs=outputs,
            sweep_funds=bool(to_satoshis == -1),
            change_address=change_address,
            coin_symbol='btc',
        )

        if not tx_is_correct:
            raise Exception('TX Verification Error: %s' % err_msg)

        # Sign transaction locally:
        privkey_list, pubkey_list = [], []

        for _ in unsigned_tx['tx']['inputs']:
            privkey_list.append(from_privkey)
            pubkey_list.append(from_pubkey)

        logger.info('privkeyhex_list: %s' % privkey_list)
        logger.info('pubkeyhex_list: %s' % pubkey_list)

        tx_signatures = blockcypher.make_tx_signatures(
            txs_to_sign=unsigned_tx['tosign'],
            privkey_list=privkey_list,
            pubkey_list=pubkey_list,
        )
        logger.info('tx_signatures: %s' % tx_signatures)

        # Broadcast transaction:
        broadcasted_tx = blockcypher.broadcast_signed_transaction(
            unsigned_tx=unsigned_tx,
            signatures=tx_signatures,
            pubkeys=pubkey_list,
            coin_symbol='btc',
        )
        logger.info('broadcasted_tx: %s' % broadcasted_tx)

        if 'errors' in broadcasted_tx:
            logger.warning('TX Error(s): Tx May NOT Have Been Broadcast')
            for error in broadcasted_tx['errors']:
                logger.error(error['error'])

        tx_hash = broadcasted_tx['tx']['hash']

        # Save Transaction Data:
        tx.external_id = tx_hash
        tx.data = broadcasted_tx['tx']
        tx.save()

        return tx_hash

    def get_balance(self):
        api_key = getattr(settings, 'BLOCKCYPHER_TOKEN')
        return blockcypher.get_total_balance(self.get_account_id(), api_key=api_key)


class AbstractReceiveWebhookInterfaceBase:
    def __init__(self, account):
        # Always linked to an AdminAccount
        self.account = account

    def subscribe_to_all(self):
        raise NotImplementedError('subclasses of AbstractBaseUser must provide a get_account_id() method')

    def unsubscribe_from_all(self):
        raise NotImplementedError('subclasses of AbstractBaseUser must provide a get_account_id() method')


class WebhookReceiveInterface(AbstractReceiveWebhookInterfaceBase):
    def blockcypher_receive_unconfirmed(self):
        from .models import ReceiveWebhook
        api_key = settings.BLOCKCYPHER_TOKEN
        # base_url = urljoin(BASE_URL, 'unconfirmed')
        request = None
        base_url = ''.join(['https://', get_current_site(request).domain, '/api/1', '/hooks', '/unconfirmed/'])

        # ID is used to keep track of user or tx for which transactions are being monitored:
        params = {'id': self.account.id}
        callback_url = base_url + ('&', '?')[urlparse(base_url).query == ''] + urlencode(params)

        url = 'https://api.blockcypher.com/v1/btc/main/hooks'
        params = {
            'secret': 'secret'  # TODO: set proper secret
        }

        data = {'event': 'unconfirmed-tx',
                'url': callback_url,
                'address': self.account.account_id,
                'token': api_key}

        res = requests.post(url, params=params, json=data, verify=True)
        webhook_id = res.json()['id']

        ReceiveWebhook.objects.create(user_account=self.account,
                                      webhook_type='unconfirmed-tx',
                                      webhook_id=webhook_id,
                                      callback_url=callback_url)

    def blockcypher_receive_confirmations(self):
        from .models import ReceiveWebhook
        api_key = settings.BLOCKCYPHER_TOKEN
        # TODO: Remove hardcoded SITE_URL
        # base_url = urljoin(BASE_URL, 'unconfirmed')
        request = None
        base_url = ''.join(['https://', get_current_site(request).domain, '/api/1', '/hooks', '/confirmations/'])
        params = {'id': self.account.id}
        callback_url = base_url + ('&', '?')[urlparse(base_url).query == ''] + urlencode(params)

        url = 'https://api.blockcypher.com/v1/btc/main/hooks'
        params = {
            'secret': 'secret'  # TODO: set proper secret
        }

        data = {'event': 'tx-confirmation',
                'url': callback_url,
                'address': self.account.account_id,
                'token': api_key}

        res = requests.post(url, params=params, json=data, verify=True)
        print(res.json())
        webhook_id = res.json()['id']

        ReceiveWebhook.objects.create(user_account=self.account,
                                      webhook_type='tx-confirmation',
                                      webhook_id=webhook_id,
                                      callback_url=callback_url)

    def blockcypher_receive_confidence(self, confidence_factor: float = 0.99):
        from .models import ReceiveWebhook
        api_key = settings.BLOCKCYPHER_TOKEN
        # TODO: Remove hardcoded SITE_URL
        # base_url = urljoin(BASE_URL, 'confirmations')
        request = None
        base_url = ''.join(['https://', get_current_site(request).domain, '/api/1', '/hooks', '/confidence/'])
        params = {'id': self.account.id}
        callback_url = base_url + ('&', '?')[urlparse(base_url).query == ''] + urlencode(params)

        url = 'https://api.blockcypher.com/v1/btc/main/hooks'

        data = {'event': 'tx-confidence',
                'confidence': confidence_factor,
                'url': callback_url,
                'address': self.account.account_id,
                'token': api_key}

        res = requests.post(url, json=data, verify=True)
        webhook_id = res.json()['id']
        logger.info(res.json())
        logger.info(webhook_id)

        ReceiveWebhook.objects.create(user_account=self.account,
                                      webhook_type='tx-confidence',
                                      webhook_id=webhook_id,
                                      callback_url=callback_url)

    def unsubscribe_blockcypher(self, webhook_type: str):
        webhook_set = self.account.receivewebhook_set
        selected_hooks = webhook_set.filter(webhook_type=webhook_type)

        for hook in selected_hooks:
            # TODO: fix manual blockcypher call:
            logger.info(hook.webhook_id)
            url = 'https://api.blockcypher.com/v1/btc/main/hooks/' + hook.webhook_id
            params = {'token': settings.BLOCKCYPHER_TOKEN}
            res = requests.delete(url=url, params=params, verify=True)
            return res

    def subscribe_to_all(self):
        self.blockcypher_receive_confidence()
        # The confirmations hook also posts the unconfirmed tx
        self.blockcypher_receive_confirmations()

    def unsubscribe_from_all(self):
        self.unsubscribe_blockcypher('unconfirmed-tx')
        self.unsubscribe_blockcypher('tx-confidence')
