# -*- coding: utf-8 -*-
# Home-video availability lookup against blu-ray.com.
#
# Used by the widget "dubbed content" filter as the FALLBACK signal: it is queried only when a title
# is NOT found on any streaming platform (TMDb/JustWatch) in the user's country, to decide whether a
# physical/home-video edition exists there (a strong hint that a localised, i.e. dubbed, edition exists).
#
# Mechanism (verified): blu-ray.com localises its "Releases" block via a `country` cookie. quicksearch
# resolves the title to a product id; menu_ajax?action=showreleases then returns ONLY that country's
# releases, each under an <h2 class="oswaldcollection"> header carrying the country flag. A title with
# NO release in that country instead returns a "No releases from <flag>" placeholder -- which STILL
# contains the flag image, so flag-presence alone is a false positive. The reliable discriminator is the
# oswaldcollection header followed by the country flag (the original working pattern).
import re
import requests

_SEARCH_URL = 'https://www.blu-ray.com/search/quicksearch.php'
_AJAX_URL = 'https://www.blu-ray.com/products/menu_ajax.php?p=%s&action=showreleases'
_URL_RE = re.compile(r"var urls = new Array\('([^']+)'")
# Per-format release product pages linked inside the releases block (one per edition: 4K, Blu-ray, DVD).
_RELEASE_URL_RE = re.compile(r'href="(https://www\.blu-ray\.com/movies/[^"]+?/\d+/)"')
# Marker shown on a release page that is announced but NOT yet on sale. A freshly out-of-cinemas title can
# have ONLY such pre-order listings, which don't mean a dubbed edition is actually available yet.
_PREORDER_MARK = 'Available for pre-order'
# Cap on release pages fetched per title when verifying (each is a heavy full HTML page).
_MAX_RELEASE_CHECKS = 4
_HEADERS = {
	'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
	'Accept': '*/*',
	'X-Requested-With': 'XMLHttpRequest',
	'Referer': 'https://www.blu-ray.com/'
}
_TIMEOUT = 8.0

# Lazily-built shared session. Built with plain requests (no kodi_utils dependency) so the module stays
# importable/testable outside Kodi. Cookies are passed PER-REQUEST (never mutating session state) so the
# shared session is safe to use from the parallel per-item filter threads.
_session = None

def _get_session():
	global _session
	if _session is None:
		s = requests.Session()
		s.mount('https://', requests.adapters.HTTPAdapter(pool_maxsize=8))
		s.headers.update(_HEADERS)
		_session = s
	return _session

def _release_pattern(country):
	return re.compile(r'<h2 class="oswaldcollection"[^>]*>.*?flags/%s\.png' % re.escape(country), re.IGNORECASE | re.DOTALL)

def has_home_video_release(title, year, country='IT', verify_released=False):
	# Returns:
	#   True  -> a home-video release exists for `title` in `country`
	#   False -> conclusively no release (title not on blu-ray.com, or "No releases from <country>")
	#   None  -> network/parse error: INCONCLUSIVE. The caller must fail open (show the item) and NOT cache.
	# verify_released: when True, a matched release is additionally confirmed to be actually on sale (not
	# only announced / "Available for pre-order"). This costs extra heavy page fetches, so the caller sets
	# it only for recently-released titles where an announced-but-not-out edition is plausible. See dub_filter.
	if not title: return None
	country = country.upper()
	cookies = {'country': country.lower()}
	keyword = '%s %s' % (title, year) if year else title
	payload = {'section': 'theatrical', 'userid': '-1', 'country': country, 'keyword': keyword}
	try:
		session = _get_session()
		res = session.post(_SEARCH_URL, data=payload, cookies=cookies, timeout=_TIMEOUT)
		res.raise_for_status()
		match = _URL_RE.search(res.text)
		if not match or not match.group(1):
			return False
		movie_id = match.group(1).strip('/').split('/')[-1]
		rel = session.get(_AJAX_URL % movie_id, cookies=cookies, timeout=_TIMEOUT)
		rel.raise_for_status()
		block = rel.text
		if not _release_pattern(country).search(block):
			return False
		if not verify_released:
			return True
		return _any_released(block, cookies, session)
	except requests.exceptions.RequestException:
		return None
	except Exception:
		return None

def _any_released(block, cookies, session):
	# True if at least one of the country's listed release editions is actually on sale, False if every one
	# is pre-order only, None if a release page couldn't be fetched (inconclusive -> caller fails open).
	urls = list(dict.fromkeys(_RELEASE_URL_RE.findall(block)))
	if not urls: return True  # releases exist but no parseable per-edition link -> assume available (keep)
	for url in urls[:_MAX_RELEASE_CHECKS]:
		try:
			page = session.get(url, cookies=cookies, timeout=_TIMEOUT)
			page.raise_for_status()
		except requests.exceptions.RequestException:
			return None
		if _PREORDER_MARK not in page.text:
			return True
	return False
