from logging import getLogger

from decimal import Decimal
from django.contrib.postgres.fields import JSONField
from django.db import models

from .api import Interface

logger = getLogger('django')


class MoneyField(models.DecimalField):
    """Decimal Field with hardcoded precision of 28 and a scale of 18."""

    def __init__(self, verbose_name=None, name=None, max_digits=28,
                 decimal_places=18, **kwargs):
        super(MoneyField, self).__init__(verbose_name, name, max_digits, decimal_places, **kwargs)


# Log of all receive transactions processed.
class ReceiveTransaction(models.Model):
    STATUS = (
        ('Waiting', 'Waiting'),
        ('Pending', 'Pending'),
        ('Complete', 'Complete'),
        ('Failed', 'Failed'),
    )
    user_account = models.ForeignKey('adapter.UserAccount')
    external_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    rehive_code = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    recipient = models.CharField(max_length=200, null=True, blank=True)
    amount = MoneyField(default=Decimal(0))
    currency = models.CharField(max_length=200, null=True, blank=True)
    issuer = models.CharField(max_length=200, null=True, blank=True)
    rehive_response = JSONField(null=True, blank=True, default={})
    status = models.CharField(max_length=24, choices=STATUS, null=True, blank=True, db_index=True)
    data = JSONField(null=True, blank=True, default={})
    metadata = JSONField(null=True, blank=True, default={})

    def upload_to_rehive(self):
        from .tasks import create_rehive_receive, confirm_rehive_transaction
        if not self.rehive_code:
            if self.status in ['Pending', 'Complete']:
                create_rehive_receive(self.id)
        else:
            if self.status == 'Complete':
                confirm_rehive_transaction(self.id)


# Log of all processed sends.
class SendTransaction(models.Model):
    STATUS = (
        ('Pending', 'Pending'),
        ('Complete', 'Complete'),
    )
    TYPE = (
        ('send', 'Send'),
        ('receive', 'Receive'),
    )
    admin_account = models.ForeignKey('adapter.AdminAccount')
    external_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    rehive_code = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    recipient = models.CharField(max_length=200, null=True, blank=True)
    amount = MoneyField(default=Decimal(0))
    currency = models.CharField(max_length=200, null=True, blank=True)
    issuer = models.CharField(max_length=200, null=True, blank=True)
    rehive_request = JSONField(null=True, blank=True, default={})
    data = JSONField(null=True, blank=True, default={})
    metadata = JSONField(null=True, blank=True, default={})

    def execute(self):
        account = AdminAccount.objects.get(default=True)
        account.process_send(self)


# Accounts for identifying Rehive users.
# Passive account, receive only.
class UserAccount(models.Model):
    rehive_id = models.CharField(max_length=100, null=True, blank=True)  # id for identifying user on rehive
    account_id = models.CharField(max_length=200, null=True, blank=True)  # crypto address
    admin_account = models.ForeignKey('adapter.AdminAccount')
    metadata = JSONField(null=True, blank=True, default={})

    def save(self, *args, **kwargs):
        if not self.id:  # On create
            logger.info('Fetching account_id.')
            self.account_id = self._new_account_id()
        return super(UserAccount, self).save(*args, **kwargs)

    def _new_account_id(self):
        interface = Interface(account=self.admin_account)
        return interface.get_user_account_id(user_id=self.rehive_id)


# HotWallet/ Operational Accounts for sending or receiving on behalf of users.
# Admin accounts usually have a secret key to authenticate with third-party provider (or XPUB for key generation).
class AdminAccount(models.Model):
    name = models.CharField(max_length=100, null=True, blank=True)
    rehive_id = models.CharField(max_length=100, null=True, blank=True)  # id for identifying admin on rehive
    type = models.CharField(max_length=100, null=True, blank=True)  # some more descriptive info.
    secret = JSONField(null=True, blank=True, default={})  # crypto seed, private key or XPUB
    metadata = JSONField(null=True, blank=True, default={})
    default = models.BooleanField(default=False)

    def send(self, tx: SendTransaction) -> bool:
        """
        Initiates a send transaction using the Admin account.
        """
        interface = Interface(account=self)
        interface.send(tx)
        return True

    # Return account id (e.g. Bitcoin address)
    def get_account_id(self) -> str:
        """
        Returns third party identifier of Admin account. E.g. Bitcoin address.
        """
        interface = Interface(account=self)
        return interface.get_account_id()

    def get_balance(self) -> int:
        interface = Interface(account=self)
        return interface.get_balance()


class ReceiveWebhook(models.Model):
    webhook_type = models.CharField(max_length=50, null=True, blank=True)
    webhook_id = models.CharField(max_length=50, null=True, blank=True)
    receive_transaction = models.ForeignKey(UserAccount)
    callback_url = models.CharField(max_length=150, blank=False)
