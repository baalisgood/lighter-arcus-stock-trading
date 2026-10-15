"""Constrain the pinned SDK's authenticated HTTP transport."""
from urllib.parse import urlsplit


def harden_client(client, base_url):
    session = client.rest_client.pool_manager
    if getattr(session, '_stock_transport_hardened', False):
        return client
    original = session._request
    expected = urlsplit(base_url)
    async def request(method, url, **kwargs):
        actual = urlsplit(str(url))
        if (actual.scheme, actual.hostname, actual.port) != (expected.scheme, expected.hostname, expected.port):
            raise ValueError('Lighter request destination rejected')
        kwargs['allow_redirects'] = False
        response = await original(method, url, **kwargs)
        if 300 <= response.status < 400:
            response.close()
            raise ValueError('Lighter redirect rejected')
        return response
    session._request = request
    session._trust_env = False
    session._stock_transport_hardened = True
    return client
