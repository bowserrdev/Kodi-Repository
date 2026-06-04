import sys
import os
import json

# ==========================================
# 1. MOCK KODI ENVIRONMENT
# ==========================================
MOCK_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mock_data')
os.makedirs(MOCK_DATA_DIR, exist_ok=True)

class MockAddon:
    def __init__(self, id=None): pass
    def getAddonInfo(self, info):
        if info == 'profile': return MOCK_DATA_DIR
        if info == 'path': return MOCK_DATA_DIR
        return 'MockInfo'
    def getLocalizedString(self, info): return 'MockString'
    def getSetting(self, id): return 'false'
    def setSetting(self, id, val): pass

class MockXbmcAddon:
    Addon = MockAddon

class MockMonitor:
    def abortRequested(self): return False
    def waitForAbort(self, timeout=None): pass

class MockXbmc:
    Monitor = MockMonitor
    def getCondVisibility(self, cond): return True
    def getInfoLabel(self, label): return '20.0'
    def executebuiltin(self, cmd): pass
    def executeJSONRPC(self, cmd): return '{}'
    def sleep(self, time): pass
    def log(self, msg, level=0): pass
    LOGINFO = 1; LOGWARNING = 2; LOGERROR = 3; LOGDEBUG = 0

class MockDialog:
    def notification(self, *a, **k): pass
    def yesno(self, *a, **k): return True
    def select(self, *a, **k): return 0
    def multiselect(self, *a, **k): return []

class MockWindow:
    def __init__(self, id): self.props = {}
    def getProperty(self, key): return self.props.get(key, '')
    def setProperty(self, key, val): self.props[key] = val
    def clearProperty(self, key): self.props.pop(key, None)

class MockDialogProgress:
    def create(self, *a): pass
    def update(self, *a): pass
    def iscanceled(self): return False
    def close(self): pass

class MockXbmcGui:
    Dialog = MockDialog
    Window = MockWindow
    DialogProgress = MockDialogProgress

class MockFile:
    def __init__(self, filepath, mode='r'): pass
    def read(self): return ''
    def write(self, data): pass
    def close(self): pass

class MockXbmcVfs:
    File = MockFile
    def translatePath(self, path):
        if 'profile' in path or 'addon_data' in path:
            return MOCK_DATA_DIR
        return path.replace('special://', '%s/' % MOCK_DATA_DIR)
    def exists(self, path): return os.path.exists(path)
    def mkdir(self, path): os.makedirs(path, exist_ok=True)
    def mkdirs(self, path): os.makedirs(path, exist_ok=True)
    def delete(self, path): pass
    def rename(self, path, path2): pass

sys.modules['xbmc'] = MockXbmc()
sys.modules['xbmcaddon'] = MockXbmcAddon()
sys.modules['xbmcgui'] = MockXbmcGui()
sys.modules['xbmcvfs'] = MockXbmcVfs()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cocoscrapers.modules.log_utils as log_utils
log_utils.log = lambda msg, *a, **k: print('[LOG] %s' % msg)
log_utils.error = lambda msg=None, *a, **k: __import__('traceback').print_exc()


# ==========================================
# 2. CONFIGURAZIONE PROXY (modifica qui)
# ==========================================
PROXY_URL = "http://1cdaa1484d0a4928be55__cr.it:1c3b6040f069bbf7@gw.dataimpulse.com:823" # es: 'http://user:pass@gw.dataimpulse.com:823' — lascia vuoto per disabilitare

import cocoscrapers.modules.control as control
_SETTINGS = {
    'proxy.enabled': 'true' if PROXY_URL else 'false',
    'proxy.url': PROXY_URL,
    'filter.undesirables': 'false',
    'filter.foreign.single.audio': 'false',
}
control.setting = lambda x, y=None: _SETTINGS.get(x, 'false')


# ==========================================
# 3. TEST IP — verifica che il proxy funzioni
# ==========================================
def test_proxy():
    import requests
    print('\n' + '='*60)
    print('TEST PROXY')
    print('='*60)
    try:
        ip_diretto = requests.get('https://api.ipify.org?format=json', timeout=5).json()['ip']
        print('IP diretto: %s' % ip_diretto)
    except Exception as e:
        print('Errore IP diretto: %s' % e)
        return

    if not PROXY_URL:
        print('Proxy non configurato, skip.')
        return

    try:
        proxies = {'http': PROXY_URL, 'https': PROXY_URL}
        ip_proxy = requests.get('https://api.ipify.org?format=json', timeout=5, proxies=proxies).json()['ip']
        print('IP proxy:   %s' % ip_proxy)
        if ip_diretto != ip_proxy:
            print('Proxy funziona correttamente.')
        else:
            print('ATTENZIONE: IP identici, il proxy potrebbe non funzionare.')
    except Exception as e:
        print('Errore connessione proxy: %s' % e)


# ==========================================
# 4. TEST RAW API — verifica campi risposta
# ==========================================
def test_raw_api(imdb_id='tt7888964', media_type='movie', season=None):
    import math, time, secrets, requests

    BASE_URL = 'https://debridmediamanager.com'
    SALT = 'debridmediamanager.com%%fe7#td00rA3vHz%VmI'

    def _js_imul(a, b): return (a * b) & 0xFFFFFFFF
    def _urshift(val, n): return (val & 0xFFFFFFFF) >> n
    def _hash_func(s):
        i = 0xdeadbeef ^ len(s)
        t = 0x41c6ce57 ^ len(s)
        for ch in s:
            l = ord(ch)
            xi = _js_imul(i ^ l, 0x9e3779b1)
            i = ((xi << 5) & 0xFFFFFFFF | _urshift(xi, 27)) & 0xFFFFFFFF
            xt = _js_imul(t ^ l, 0x5f356495)
            t = ((xt << 5) & 0xFFFFFFFF | _urshift(xt, 27)) & 0xFFFFFFFF
        i = (i + _js_imul(t, 0x5d588b65)) & 0xFFFFFFFF
        t = (t + _js_imul(i, 0x78a76a79)) & 0xFFFFFFFF
        return format(_urshift(i ^ t, 0), 'x')
    def solve():
        rand_hex = format(secrets.randbits(32), 'x')
        key = '%s-%s' % (rand_hex, int(time.time()))
        ha = _hash_func(key)
        hb = _hash_func('%s-%s' % (SALT, rand_hex))
        half = math.floor(len(ha) / 2)
        interleaved = ''.join(ha[x] + hb[x] for x in range(half))
        return key, interleaved + hb[half:][::-1] + ha[half:][::-1]

    api_type = 'tv' if media_type in ('tv', 'series') else 'movie'
    frontend_type = 'show' if api_type == 'tv' else 'movie'
    api_url = '%s/api/torrents/%s' % (BASE_URL, api_type)
    ref_url = '%s/%s/%s' % (BASE_URL, frontend_type, imdb_id)
    if api_type == 'tv' and season:
        ref_url += '/%s' % season

    key, solution = solve()
    params = {'imdbId': imdb_id, 'dmmProblemKey': key, 'solution': solution,
              'onlyTrusted': 'false', 'maxSize': 0, 'page': 0}
    if api_type == 'tv' and season is not None:
        params['seasonNum'] = season

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': BASE_URL,
        'Referer': ref_url,
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
    }

    proxies = {'http': PROXY_URL, 'https': PROXY_URL} if PROXY_URL else None

    print('\n' + '='*60)
    print('RAW API TEST — page 0')
    print('='*60)
    resp = requests.get(api_url, params=params, headers=headers, timeout=(2, 15), proxies=proxies)
    print('Status: %s' % resp.status_code)
    if resp.status_code != 200:
        print('ERRORE: %s' % resp.text[:300])
        return
    results = resp.json().get('results', [])
    print('Risultati: %d' % len(results))
    if results:
        print('\n--- PRIMO RISULTATO RAW ---')
        print(json.dumps(results[0], indent=2, ensure_ascii=False))
        print('\n--- CAMPI DISPONIBILI ---')
        all_keys = set()
        for r in results: all_keys.update(r.keys())
        print(sorted(all_keys))


# ==========================================
# 5. TEST SCRAPER COMPLETO
# ==========================================
def test_scraper(imdb_id, title, year, media_type='movie', season=None, episode=None, tvshowtitle=None):
    from cocoscrapers.sources_cocoscrapers.torrents.dmm import source

    scraper = source()

    if media_type == 'movie':
        data = {'imdb': imdb_id, 'title': title, 'year': year, 'aliases': []}
    else:
        data = {
            'imdb': imdb_id,
            'tvshowtitle': tvshowtitle or title,
            'title': '',
            'year': year,
            'season': str(season),
            'episode': str(episode),
            'aliases': []
        }

    print('\n' + '='*60)
    print('SCRAPER TEST — %s (%s)%s' % (title, year, ' [proxy: ON]' if PROXY_URL else ' [proxy: OFF]'))
    print('='*60)

    risultati = scraper.sources(data, {})

    if not risultati:
        print('Nessun risultato.')
        return

    risultati.sort(key=lambda x: x.get('size', 0), reverse=True)
    print('Trovati %d risultati:\n' % len(risultati))
    for i, r in enumerate(risultati[:20]):
        print('[%2d] %s | %.2f GB | Seeders: %s' % (
            i+1, r.get('quality', '?'), r.get('size', 0), r.get('seeders', 0)))
        print('     %s' % r.get('name', ''))
        print('     hash: %s...' % r.get('hash', '')[:16])
    if len(risultati) > 20:
        print('... e altri %d risultati.' % (len(risultati) - 20))


# ==========================================
# 6. MAIN
# ==========================================
if __name__ == '__main__':
    print('\n' + '='*60)
    print('      DMM SCRAPER TEST')
    print('Proxy: %s' % (PROXY_URL if PROXY_URL else 'disabilitato'))
    print('='*60)

    test_proxy_choice = input('\nTest IP proxy? [s/N]: ').strip().lower()
    if test_proxy_choice == 's':
        test_proxy()

    print('\n1 = Film')
    print('2 = Serie TV')
    media_type = input('Tipo [1]: ').strip() or '1'

    if media_type == '1':
        imdb = input('IMDB ID [tt7888964 = Nobody 2021]: ').strip() or 'tt7888964'
        title = input('Titolo [Nobody]: ').strip() or 'Nobody'
        year = input('Anno [2021]: ').strip() or '2021'

        raw = input('Vedere risposta raw API? [s/N]: ').strip().lower()
        if raw == 's':
            test_raw_api(imdb, 'movie')

        test_scraper(imdb, title, year, 'movie')
    else:
        imdb = input('IMDB ID [tt3581920 = The Last of Us]: ').strip() or 'tt3581920'
        title = input('Titolo serie [The Last of Us]: ').strip() or 'The Last of Us'
        year = input('Anno [2023]: ').strip() or '2023'
        season = input('Stagione [1]: ').strip() or '1'
        episode = input('Episodio [1]: ').strip() or '1'

        raw = input('Vedere risposta raw API? [s/N]: ').strip().lower()
        if raw == 's':
            test_raw_api(imdb, 'tv', season)

        test_scraper(imdb, title, year, 'tv', int(season), int(episode), title)