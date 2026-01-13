'''
Manages connections to YouTube for data import.
'''

from anyio import sleep
from random import random
from logging import Logger
from logging import getLogger

from httpx import AsyncClient
from httpx import Response
from httpx import ReadTimeout

_LOGGER: Logger = getLogger(__name__)

YOUTUBE_DOMAIN: str = '.youtube.com'


class AsyncYouTubeClient(AsyncClient):
    HEADERS: dict[str, str] = {
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': (
            'text/html,application/xhtml+xml,'
            'application/xml;q=0.9,*/*;q=0.8'
        ),
    }
    USER_AGENT: str = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )

    CONSENT_COOKIES: dict[str, str] = {
        'CONSENT': 'YES+cb.20210328-17-p0.en+FX+100',
        'SOCS': (
            'CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjM'
            'wODI5LjA3X3AwGgJlbiADGgYIgICUoQY'
        ),
    }
    '''
    An HTTP client for connecting to YouTube.
    '''
    SCRAPE_URL: str = 'https://www.youtube.com'

    def __init__(self, user_agent: str | None = None,
                 consent_cookies: dict[str, str] | None = None,
                 use_consent_cookies: bool = True, **kwargs,
                 ) -> None:
        '''
        Initializes the YouTube client.

        :param kwargs: Additional arguments to pass to the HTTP client.
        '''

        super().__init__(**kwargs)
        self.headers.update(self.HEADERS)

        if user_agent:
            self.headers['User-Agent'] = user_agent

        self.consent_cookies: dict[str, str] | None = consent_cookies
        if use_consent_cookies and self.consent_cookies:
            # Set consent cookies to bypass consent pages
            for cookie_name, value in self.consent_cookies.items() or {}:
                self.cookies.set(
                    cookie_name, value, domain=YOUTUBE_DOMAIN, path='/'
                )

    def get_headers(self) -> dict[str, str]:
        '''
        Get the current HTTP headers for the client.

        :returns: A dictionary of HTTP headers.
        '''

        return dict(self.headers)

    async def get(self, url: str, delay: int | None = None, **kwargs
                  ) -> str | None:
        '''
        Performs a GET request to the specified URL.

        :param url: The URL to send the GET request to.
        :param kwargs: Additional arguments to pass to the GET request.

        :returns: The HTTP response.
        '''

        log_extra: dict = {'url': url}

        try:
            _LOGGER.debug(f'HTTP GET {url}', extra=log_extra)
            resp: Response = await super().get(url, **kwargs)
        except ReadTimeout as exc:
            _LOGGER.debug(
                f'HTTP GET for {url} timed out: {exc}', extra=log_extra
            )
            raise RuntimeError(f'Timeout fetching URL {url}')

        if (resp.status_code == 303
                and 'youtube.com' in resp.headers.get('Location', '')):
            # Follow redirect just once if it redirects to another YouTube URL
            resp = await super().get(resp.headers['Location'], **kwargs)

        if resp.status_code != 200:
            _LOGGER.warning(
                f'HTTP scrape for {self.youtube_url} failed: '
                f'{resp.status_code}', extra=log_extra
            )
            return None

        if delay:
            await self._delay()

        return resp.text

    @staticmethod
    async def _delay(min: int = 2, max: int = 5) -> None:
        await sleep(random() * (max - min) + min)

    async def get_consent_cookies(self, timeout: int = 3) -> dict[str, str]:
        '''
        Fetch consent cookies from YouTube.

        Returns a dictionary of cookies that can be used for subsequent
        YouTube requests to bypass the consent dialog.

        :param timeout: Request timeout in seconds
        :returns: Dictionary of cookie name -> cookie value
        '''

        # Standard headers to mimic a browser
        headers: dict[str, str] = {
            'User-Agent': self.USER_AGENT,
            'Accept': (
                'text/html,application/xhtml+xml,application/xml;q=0.9,'
                'image/webp,*/*;q=0.8'
            ),
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

        # First request to YouTube to get initial cookies
        response: Response = await super().get(
            f'https://www{YOUTUBE_DOMAIN}/',
            headers=headers, timeout=timeout
        )

        # Check if we got a consent page
        if ('consent.youtube.com' in response.text
                or 'CONSENT' not in response.cookies):
            # Try to extract and submit consent
            # YouTube uses a SOCS cookie for consent in newer implementations

            # Set consent cookie directly (simulates accepting cookies)
            # SOCS cookie format: CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjMxMDE2LjA3X3Ax...   # noqa: E501
            # This is a base64 encoded consent acceptance

            self.cookies.set(
                'CONSENT',
                'PENDING+987',  # Initial pending state
                domain=YOUTUBE_DOMAIN,
                path='/'
            )

            # Make another request to potentially get updated cookies
            response: Response = await super().get(
                f'https://www{YOUTUBE_DOMAIN}/', headers=headers,
                timeout=timeout
            )

            # YouTube now primarily uses SOCS cookie
            # We can set a pre-accepted consent value
            # self.cookies.set(
            #     'SOCS',
            #     'CAISHAgBEhJnd3NfMjAyMzEwMTYtMF9SQzEaAmVuIAEaBgiA_LyaBg',
            #     domain='.youtube.com',
            #     path='/'
            # )

        # Extract all cookies as a dictionary
        cookies_dict: dict[str, str] = {}
        for cookie_name, cookie in response.cookies.items():
            self.cookies.set(
                cookie_name, cookie, domain=YOUTUBE_DOMAIN, path='/'
            )
            cookies_dict[cookie_name] = cookie

        return cookies_dict

    def create_cookie_header(self, cookies: dict) -> str:
        '''
        Convert a cookies dictionary to a Cookie header string.

        :param cookies: Dictionary of cookie name -> value

        :returns: String formatted for use in Cookie HTTP header
        '''

        return '; '.join(f'{name}={value}' for name, value in cookies.items())
