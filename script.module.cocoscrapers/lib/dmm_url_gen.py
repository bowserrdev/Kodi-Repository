import math, time, secrets
from urllib.parse import urlencode

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

imdb  = input('IMDB ID [tt7888964]: ').strip() or 'tt7888964'
mtype = input('Tipo (movie/tv) [movie]: ').strip() or 'movie'
season = None
if mtype == 'tv':
    season = input('Stagione [1]: ').strip() or '1'

key, solution = solve()
params = {
    'imdbId': imdb,
    'dmmProblemKey': key,
    'solution': solution,
    'onlyTrusted': 'false',
    'maxSize': 0,
    'page': 0,
}
if mtype == 'tv' and season:
    params['seasonNum'] = season

url = 'https://debridmediamanager.com/api/torrents/%s?%s' % (mtype, urlencode(params))
frontend = 'show' if mtype == 'tv' else 'movie'
referer = 'https://debridmediamanager.com/%s/%s' % (frontend, imdb)
if mtype == 'tv' and season:
    referer += '/%s' % season

print('\n' + '='*60)
print('URL (incolla in Insomnia come GET):')
print(url)
print('\nHeaders da aggiungere in Insomnia:')
print('  Origin:  https://debridmediamanager.com')
print('  Referer: %s' % referer)
print('  Accept:  application/json, text/plain, */*')
print('  User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0')
print('\nATTENZIONE: il challenge scade ~30s, incolla subito in Insomnia.')
print('='*60)