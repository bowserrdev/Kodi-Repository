# -*- coding: utf-8 -*-

import re
from random import choice, randrange
from threading import Lock
from html import unescape
from urllib.parse import urlparse
import requests
from requests.adapters import HTTPAdapter
from cocoscrapers.modules import cache
from cocoscrapers.modules import dom_parser

_session_pool = {}
_pool_lock = Lock()


def _get_session(url):
	netloc = urlparse(url).netloc
	with _pool_lock:
		if netloc not in _session_pool:
			s = requests.Session()
			adapter = HTTPAdapter(pool_connections=2, pool_maxsize=10)
			s.mount('https://', adapter)
			s.mount('http://', adapter)
			_session_pool[netloc] = s
		return _session_pool[netloc]


def _get_configured_proxy():
	try:
		from cocoscrapers.modules.control import setting as getSetting
		if getSetting('proxy.enabled') != 'true':
			return None
		proxy = (getSetting('proxy.url') or '').strip()
		return proxy if proxy else None
	except:
		return None


def request(url, close=True, redirect=True, error=False, proxy=None, post=None, headers=None, mobile=False,
			XHR=False, limit=None, referer=None, cookie=None, compression=True, output='', timeout='30',
			verifySsl=True, flare=True, ignoreErrors=None, as_bytes=False):
	try:
		if not url: return None
		if url.startswith('//'): url = 'http:' + url

		session = _get_session(url)

		req_headers = {}
		if not (headers and 'User-Agent' in headers):
			req_headers['User-Agent'] = 'Apple-iPhone/701.341' if mobile else cache.get(randomagent, 12)
		if headers:
			req_headers.update(headers)
		if referer:
			req_headers.setdefault('Referer', referer)
		req_headers.setdefault('Accept-Language', 'en-US')
		if XHR:
			req_headers.setdefault('X-Requested-With', 'XMLHttpRequest')
		if cookie:
			req_headers.setdefault('Cookie', cookie)

		if isinstance(post, dict): post_data = post
		elif isinstance(post, str): post_data = post.encode('utf-8')
		elif isinstance(post, bytes): post_data = post
		else: post_data = None

		def _send(request_proxy=None):
			return session.request(
				method='POST' if post_data is not None else 'GET',
				url=url,
				headers=req_headers,
				data=post_data,
				proxies={'http': request_proxy, 'https': request_proxy} if request_proxy else None,
				timeout=(2, int(timeout)),
				verify=verifySsl,
				allow_redirects=redirect
			)

		response = _send(proxy)
		if response.status_code == 429 and not proxy:
			fallback_proxy = _get_configured_proxy()
			if fallback_proxy:
				try:
					from cocoscrapers.modules import log_utils
					log_utils.log('CLIENT: 429 from %s, retrying with configured proxy' % urlparse(url).netloc)
				except:
					pass
				response = _send(fallback_proxy)

		# output='extended' is always returned regardless of status so callers can inspect the code
		if output == 'extended':
			content = response.content
			try: text = content.decode('utf-8')
			except: text = content.decode('latin-1', errors='replace')
			return (text, str(response.status_code), dict(response.headers))

		if response.status_code >= 400:
			if ignoreErrors:
				try:
					if response.status_code != ignoreErrors and response.status_code not in ignoreErrors:
						if error is False:
							from cocoscrapers.modules import log_utils
							log_utils.error('Request-Error url=(%s)' % url)
						return None
				except:
					return None
			elif error is True and response.status_code in (401, 404, 405):
				return (response.text, str(response.status_code), dict(response.headers))
			else:
				if error is False:
					from cocoscrapers.modules import log_utils
					log_utils.error('Request-Error url=(%s)' % url)
				return None

		if output == 'cookie':
			return '; '.join('%s=%s' % (c.name, c.value) for c in response.cookies)
		elif output == 'geturl':
			return response.url
		elif output == 'headers':
			return dict(response.headers)
		elif output == 'chunk':
			content_length = int(response.headers.get('Content-Length', 0))
			if content_length < (2048 * 1024): return None
			return response.content[:16 * 1024]
		elif output == 'file_size':
			return int(response.headers.get('Content-Length', 0))

		content = response.content
		if limit is not None:
			max_bytes = 224 * 1024 if limit == '0' else int(limit) * 1024
			content = content[:max_bytes]

		if as_bytes: return content

		try: return content.decode('utf-8')
		except: return content.decode('latin-1', errors='replace')

	except:
		from cocoscrapers.modules import log_utils
		log_utils.error()
		return None


def parseDOM(html, name='', attrs=None, ret=False):
	try:
		if attrs:
			attrs = dict((key, re.compile(value + ('$' if value else ''))) for key, value in iter(attrs.items()))
		results = dom_parser.parse_dom(html, name, attrs, ret)
		if ret: results = [result.attrs[ret.lower()] for result in results]
		else: results = [result.content for result in results]
		return results
	except:
		from cocoscrapers.modules import log_utils
		log_utils.error()


def replaceHTMLCodes(txt):
	return _replaceHTMLCodes(_replaceHTMLCodes(txt))


def _replaceHTMLCodes(txt):
	try:
		if not txt: return ''
		txt = re.sub(r'(&#[0-9]+)([^;^0-9]+)', '\\1;\\2', txt)
		txt = unescape(txt)
		txt = txt.replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>') \
				 .replace("&apos;", "'").replace('&nbsp;', '').replace('&#38;', '&') \
				 .replace('&#8230;', '...').replace('&#8217;', "'").replace('&#8211;', '-')
		return txt.strip()
	except:
		from cocoscrapers.modules import log_utils
		log_utils.error()
		return txt


def cleanHTML(txt):
	txt = re.sub(r'<.+?>|</.+?>|\n', '', txt)
	return _replaceHTMLCodes(_replaceHTMLCodes(txt))


def randomagent():
	BR_VERS = [
		['%s.0' % i for i in range(120, 131)],
		['120.0.6099.129', '121.0.6167.184', '122.0.6261.128', '123.0.6312.122', '124.0.6367.207', '125.0.6422.141'],
		['11.0']
	]
	WIN_VERS = ['Windows NT 10.0', 'Windows NT 10.0', 'Windows NT 10.0']
	FEATURES = ['; Win64; x64', '; WOW64', '']
	RAND_UAS = [
		'Mozilla/5.0 ({win_ver}{feature}; rv:{br_ver}) Gecko/20100101 Firefox/{br_ver}',
		'Mozilla/5.0 ({win_ver}{feature}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{br_ver} Safari/537.36',
		'Mozilla/5.0 ({win_ver}{feature}; Trident/7.0; rv:{br_ver}) like Gecko'
	]
	index = randrange(len(RAND_UAS))
	return RAND_UAS[index].format(
		win_ver=choice(WIN_VERS),
		feature=choice(FEATURES),
		br_ver=choice(BR_VERS[index]))


def agent():
	return 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.207 Safari/537.36'
