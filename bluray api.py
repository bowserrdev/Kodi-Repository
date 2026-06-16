import requests
import re
import time

def check_italian_releases(titolo, anno):
    start_time = time.perf_counter()
    session = requests.Session()
    
    # 1. Il VERO cookie che usa Blu-ray.com per localizzare in Italia
    session.cookies.set('country', 'it', domain='.blu-ray.com')
    
    # Intestazioni per simulare fedelmente una chiamata AJAX da browser
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': 'https://www.blu-ray.com/'
    })
    
    search_url = "https://www.blu-ray.com/search/quicksearch.php"
    keyword = f"{titolo} {anno}"
    
    payload = {
        'section': 'theatrical',
        'userid': '-1',
        'country': 'IT',
        'keyword': keyword
    }
    
    try:
        # STEP 1: Eseguiamo la ricerca per trovare l'URL del film
        res_search = session.post(search_url, data=payload, timeout=5)
        res_search.raise_for_status()
        
        # Estraiamo l'URL. Esempio: 'https://www.blu-ray.com/Suspiria/28623/'
        url_match = re.search(r"var urls = new Array\('([^']+)'", res_search.text)
        
        if not url_match or not url_match.group(1):
            print("Nessun film trovato.")
            return
            
        movie_url = url_match.group(1)
        
        # Estraiamo l'ID del film dall'URL (es: 28623)
        # Togliamo l'ultimo slash e prendiamo l'ultima parte numerica
        movie_id = movie_url.strip('/').split('/')[-1]
        
        # STEP 2: OTTIMIZZAZIONE ESTREMA. 
        # Invochiamo l'API nascosta che restituisce SOLO il blocco HTML "Releases"
        ajax_url = f"https://www.blu-ray.com/products/menu_ajax.php?p={movie_id}&c=20&action=showreleases"
        
        res_releases = session.get(ajax_url, timeout=5)
        res_releases.raise_for_status()

        # STEP 3: Analisi. Dato che questo HTML contiene ESCLUSIVAMENTE la griglia
        # delle releases, basta cercare la bandierina italiana nell'header Oswald.
        pattern = r'<h2 class="oswaldcollection"[^>]*>.*?flags/IT\.png'
        
        if re.search(pattern, res_releases.text, re.IGNORECASE | re.DOTALL):
            print("ci sono releases")
        else:
            print("non ci sono releases")
            
    except requests.exceptions.RequestException as e:
        print(f"Errore di rete: {e}")

    end_time = time.perf_counter()
    print(f"Tempo totale impiegato: {end_time - start_time:.4f} secondi")

if __name__ == "__main__":
    print("Cerco...")
    check_italian_releases("Visitor Q", "2001")