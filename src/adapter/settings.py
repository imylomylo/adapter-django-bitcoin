import os

# Get the platform URL for the adapter (Rehive)
REHIVE_API_URL = os.environ.get('REHIVE_API_URL', '')

# Get the admin token for platform requests (Rehive)
REHIVE_API_TOKEN = os.environ.get('REHIVE_API_TOKEN', '')

# TODO: Replace this with user accounts and tokens.
ADAPTER_SECRET_KEY = os.environ.get('ADAPTER_TOKEN', 'secret')
BLOCKCYPHER_TOKEN = os.environ.get('BLOCKCYPHER_TOKEN', '')
