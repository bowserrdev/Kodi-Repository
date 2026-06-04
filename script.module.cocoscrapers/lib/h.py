import requests

base = 'https://rarbg-official.to'

print('=== TOKEN ===')
r = requests.get('%s/pubapi_v2.php?get_token=get_token&app_id=test' % base, timeout=5)
print('Status:', r.status_code)
print('Content-Type:', r.headers.get('Content-Type'))
print('Body:', r.text[:300])

print('\n=== SEARCH SENZA TOKEN ===')
r2 = requests.get('%s/pubapi_v2.php?mode=search&app_id=test&search_imdb=tt7888964&format=json_extended&limit=5' % base, timeout=5)
print('Status:', r2.status_code)
print('Content-Type:', r2.headers.get('Content-Type'))
print('Body:', r2.text[:300])