from collections import OrderedDict

from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.exceptions import APIException, ParseError, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import exceptions
from rest_framework.generics import GenericAPIView
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from src.adapter.utils import from_cents, create_qr_code_url, input_to_json
from .api import Interface
from .models import UserAccount, AdminAccount, SendTransaction
from .permissions import AdapterGlobalPermission

from logging import getLogger

from .throttling import NoThrottling

from .serializers import TransactionSerializer, UserAccountSerializer, AddAssetSerializer

logger = getLogger('django')


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def adapter_root(request, format=None):
    """
    ### Notes:

    To make use of this adapter:

    1) Set the Rehive webhooks for each tx type to match their corresponding endpoints below.

    2) Set a secret key for each transaction webhook

    3) Ensure the the required ENV variables have been added to the server.

    **Required ENV variables:**

    In order to use the  adapter you must set the following ENV variables on the server.

    `REHIVE_API_TOKEN` : Secret Key for authenticating with Rehive for admin functions.

    `REHIVE_API_URL` : Rehive API URL

    `ADAPTER_SECRET_KEY`: Secret Key for adapter endpoints.

    ---

    """

    return Response({'Purchase': reverse('adapter-api:purchase',
                                         request=request,
                                         format=format),
                     'Withdraw': reverse('adapter-api:withdraw',
                                         request=request,
                                         format=format),
                     'Deposit': reverse('adapter-api:deposit',
                                        request=request,
                                        format=format),
                     'Send': reverse('adapter-api:send',
                                     request=request,
                                     format=format),
                     })


class PurchaseView(GenericAPIView):
    allowed_methods = ('POST',)
    throttle_classes = (NoThrottling,)
    serializer_class = TransactionSerializer
    permission_classes = (AdapterGlobalPermission,)

    def post(self, request, *args, **kwargs):
        return Response({'status': 'success'})

    def get(self, request, *args, **kwargs):
        raise exceptions.MethodNotAllowed('GET')


class WithdrawView(GenericAPIView):
    allowed_methods = ('POST',)
    throttle_classes = (NoThrottling,)
    serializer_class = TransactionSerializer
    permission_classes = (AdapterGlobalPermission,)

    def post(self, request, *args, **kwargs):
        return Response({'status': 'success'})

    def get(self, request, *args, **kwargs):
        raise exceptions.MethodNotAllowed('GET')


class DepositView(GenericAPIView):
    allowed_methods = ('POST',)
    throttle_classes = (NoThrottling,)
    serializer_class = TransactionSerializer
    permission_classes = (AdapterGlobalPermission,)

    def post(self, request, *args, **kwargs):
        return Response({'status': 'success'})

    def get(self, request, *args, **kwargs):
        raise exceptions.MethodNotAllowed('GET')


class SendView(GenericAPIView):
    allowed_methods = ('POST',)
    throttle_classes = (NoThrottling,)
    serializer_class = TransactionSerializer
    permission_classes = (AdapterGlobalPermission,)

    def post(self, request, *args, **kwargs):
        tx_code = request.data.get('tx_code')
        to_user = request.data.get('to_user')
        amount = from_cents(request.data.get('amount'), 7)
        currency = request.data.get('currency')
        issuer = request.data.get('issuer')

        print(request.data)
        print(currency)

        logger.info('To: ' + to_user)
        logger.info('Amount: ' + str(amount))
        logger.info('Currency: ' + currency)

        tx = SendTransaction.objects.create(rehive_code=tx_code,
                                            recipient=to_user,
                                            amount=amount,
                                            currency=currency,
                                            issuer=issuer)

        tx.execute()
        return Response({'status': 'success'})

    def get(self, request, *args, **kwargs):
        raise exceptions.MethodNotAllowed('GET')


class BalanceView(APIView):
    allowed_methods = ('GET',)
    throttle_classes = (NoThrottling,)
    permission_classes = (AllowAny, AdapterGlobalPermission,)

    def post(self, request, *args, **kwargs):
        raise exceptions.MethodNotAllowed('POST')

    def get(self, request, *args, **kwargs):
        account = AdminAccount.objects.get(default=True)
        interface = Interface(account=account)
        balance = interface.get_balance()
        return Response({'balance': balance})


class OperatingAccountView(APIView):
    allowed_methods = ('GET',)
    throttle_classes = (NoThrottling,)
    permission_classes = (AllowAny, AdapterGlobalPermission,)

    def post(self, request, *args, **kwargs):
        raise exceptions.MethodNotAllowed('POST')

    def get(self, request, *args, **kwargs):
        account = AdminAccount.objects.get(default=True)
        interface = Interface(account=account)
        return Response(interface.get_account_details())


class UserAccountView(GenericAPIView):
    allowed_methods = ('POST',)
    throttle_classes = (NoThrottling,)
    permission_classes = (AllowAny, AdapterGlobalPermission,)
    serializer_class = UserAccountSerializer

    def post(self, request, *args, **kwargs):
        logger.info(request.data)
        user_id = request.data.get('user_id')
        # Check if metadata is specified:
        metadata = input_to_json(request.data.get('metadata'))
        # Generate Account ID:
        account_id = Interface.new_account_id(metadata=metadata)
        # Store Account details:
        UserAccount.objects.get_or_create(user_id=user_id, account_id=account_id)
        return Response(OrderedDict([('account_id', account_id),
                                     ('user_id', user_id)]))

    def get(self, request, *args, **kwargs):
        raise exceptions.MethodNotAllowed('GET')


class WebhookView(APIView):
    allowed_methods = ('POST',)
    permission_classes = (AllowAny,)

    def post(self, request, *args, **kwargs):
        receive_id = request.GET.get('id', '')

        if not receive_id:
            raise Exception('Bad blockcypher post: no receive_id')

        # TODO: process

        return Response({}, status=status.HTTP_200_OK)

    def get(self, request, *args, **kwargs):
        return Response({}, status=status.HTTP_404_NOT_FOUND)
