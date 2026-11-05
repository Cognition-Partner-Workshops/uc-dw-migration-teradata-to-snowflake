"""Token-scoped SQL and in-memory key-pair authentication."""

import os
import re
from datetime import datetime


def identifier(value):
    if not re.fullmatch(r'[A-Z0-9_]+', value):
        raise ValueError('Identifier must match ^[A-Z0-9_]+$')
    return '"' + value + '"'


def column_identifier(value):
    return '"' + value.replace('"', '""') + '"'


def comment(token, expires):
    identifier(token)
    parsed = datetime.fromisoformat(expires.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Expiry requires a timezone')
    return f"'run {token} expires {parsed.isoformat().replace('+00:00', 'Z')}'"


def connect():
    import snowflake.connector
    from cryptography.hazmat.primitives import serialization

    os.environ.pop('SNOWFLAKE_HOST', None)
    key = serialization.load_pem_private_key(os.environ['SNOWFLAKE_NFR_PRIVATE_KEY'].encode(), password=None)
    der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    args = dict(account=os.environ['SNOWFLAKE_NFR_ACCOUNT'], user=os.environ['SNOWFLAKE_NFR_USER'], private_key=der, authenticator='SNOWFLAKE_JWT')
    for name in ['ROLE', 'WAREHOUSE']:
        if os.environ.get('SNOWFLAKE_NFR_' + name):
            args[name.lower()] = os.environ['SNOWFLAKE_NFR_' + name]
    return snowflake.connector.connect(**args)
