import sys
import os
import importlib

# ==========================================
# 1. SETUP AMBIENTE VIRTUALE KODI
# ==========================================

# Creiamo una vera cartella sul tuo PC per ospitare i finti file di sistema di Kodi (es. cache.db)
MOCK_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mock_data')
os.makedirs(MOCK_DATA_DIR, exist_ok=True)

class MockAddon:
    def __init__(self, id=None): pass
    def getAddonInfo(self, info):
        if info == 'profile': return MOCK_DATA_DIR
        if info == 'path': return MOCK_DATA_DIR
        return "MockInfo"
    def getLocalizedString(self, info): return "MockString"
    def getSetting(self, id): return "false"
    def setSetting(self, id, val): pass

class MockXbmcAddon:
    Addon = MockAddon

class MockMonitor:
    def abortRequested(self): return False
    def waitForAbort(self, timeout=None): pass

class MockXbmc:
    Monitor = MockMonitor
    def getCondVisibility(self, cond): return True
    def getInfoLabel(self, label): return "20.0"
    def executebuiltin(self, cmd): pass
    def executeJSONRPC(self, cmd): return "{}"
    def sleep(self, time): pass
    def log(self, msg, level=0): pass
    LOGINFO = 1
    LOGWARNING = 2
    LOGERROR = 3

class MockDialog:
    def notification(self, *args, **kwargs): pass
    def yesno(self, *args, **kwargs): return True
    def select(self, *args, **kwargs): return 0
    def multiselect(self, *args, **kwargs): return []

class MockWindow:
    def __init__(self, id): self.props = {}
    def getProperty(self, key): return self.props.get(key, "")
    def setProperty(self, key, val): self.props[key] = val
    def clearProperty(self, key): self.props.pop(key, None)

class MockDialogProgress:
    def create(self, *args): pass
    def update(self, *args): pass
    def iscanceled(self): return False
    def close(self): pass

class MockXbmcGui:
    Dialog = MockDialog
    Window = MockWindow
    DialogProgress = MockDialogProgress

class MockFile:
    def __init__(self, filepath, mode='r'): pass
    def read(self): return ""
    def write(self, data): pass
    def close(self): pass

class MockXbmcVfs:
    File = MockFile
    def translatePath(self, path): 
        # Risolviamo i path speciali di Kodi verso la nostra cartella finta
        if 'profile' in path or 'addon_data' in path: 
            return MOCK_DATA_DIR
        return path.replace('special://', f'{MOCK_DATA_DIR}/')
        
    # Usiamo le vere funzioni del sistema operativo così SQLite non va in panico
    def exists(self, path): return os.path.exists(path)
    def mkdir(self, path): os.makedirs(path, exist_ok=True)
    def mkdirs(self, path): os.makedirs(path, exist_ok=True)
    def delete(self, path): pass
    def rename(self, path, path2): pass

# Installiamo i moduli finti nel sistema
sys.modules['xbmc'] = MockXbmc()
sys.modules['xbmcaddon'] = MockXbmcAddon()
sys.modules['xbmcgui'] = MockXbmcGui()
sys.modules['xbmcvfs'] = MockXbmcVfs()

# Aggiungiamo la cartella corrente al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ==========================================
# 2. OVERRIDE DELLE FUNZIONI DI COCOSCRAPERS
# ==========================================

def mock_log(msg, *args, **kwargs):
    print(f"[LOG] {msg}")

def mock_error(msg=None, *args, **kwargs):
    import traceback
    print(f"\n[ERRORE INTERNO COCOSCRAPERS] {msg if msg else ''}")
    traceback.print_exc() # Questo ci salverà la vita se ci sono altri crash nascosti

import cocoscrapers.modules.log_utils as log_utils
log_utils.log = mock_log
log_utils.error = mock_error

import cocoscrapers.modules.control as control
control.setting = lambda x, y=None: 'false' 


# ==========================================
# 3. INTERFACCIA ED ESECUZIONE
# ==========================================

def create_payload():
    print("\n" + "="*40)
    print("      COCOSCRAPERS TEST MOCK V3")
    print("="*40)
    media_type = input("Cosa vuoi cercare? (1=Film, 2=Serie TV) [1]: ").strip() or "1"
    
    data = {'aliases': []}
    
    if media_type == '1':
        data['title'] = input("Titolo Film [Nobody]: ").strip() or "Nobody"
        data['year'] = input("Anno [2021]: ").strip() or "2021"
        data['imdb'] = input("IMDB ID [tt7888964]: ").strip() or "tt7888964"
    else:
        data['tvshowtitle'] = input("Titolo Serie [The Last of Us]: ").strip() or "The Last of Us"
        data['title'] = input("Titolo Episodio [premi Invio se non lo sai]: ").strip()
        data['year'] = input("Anno uscita serie [2023]: ").strip() or "2023"
        data['imdb'] = input("IMDB ID [tt3581920]: ").strip() or "tt3581920"
        data['season'] = input("Stagione [1]: ").strip() or "1"
        data['episode'] = input("Episodio [1]: ").strip() or "1"

    return data


def run_test():
    data = create_payload()
    
    print("\nProviders disponibili: torrentio, ytsmx, torrentgalaxy, 1337x, bitsearch, ecc.")
    provider_name = input("Inserisci il provider [torrentio]: ").strip().lower()

    if not provider_name:
        provider_name = "torrentio" 

    try:
        module_path = f"cocoscrapers.sources_cocoscrapers.torrents.{provider_name}"
        scraper_module = importlib.import_module(module_path)
        scraper = scraper_module.source()
        
    except ImportError:
        print(f"\n[ERRORE] Il provider '{provider_name}' non esiste o il path è errato.")
        return
    except Exception as e:
        print(f"\n[ERRORE] Inizializzazione fallita: {e}")
        return

    print(f"\nSto interrogando {provider_name.upper()}...")
    
    try:
        risultati = scraper.sources(data, hostDict={})
    except Exception as e:
        print(f"\n[ERRORE DURANTE LO SCRAPING]: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print("\n" + "="*40)
    print("     RISULTATI RESTITUITI A FEN")
    print("="*40)
    if not risultati:
        print("Nessun risultato trovato.")
    else:
        print(f"Trovati {len(risultati)} risultati:\n")
        try:
            risultati.sort(key=lambda x: x.get('size', 0), reverse=True)
        except:
            pass

        for i, res in enumerate(risultati[:20]): # Mostro solo i primi 20 per non intasare lo schermo
            qual = res.get('quality', 'UNK')
            size = res.get('info', '').split(' | ')[0] if res.get('info') else '0 GB'
            seeders = res.get('seeders', 0)
            print(f"[{i+1}] {qual} | {size} | Seeders:{seeders}")
            print(f"    Nome: {res.get('name')}")
            print(f"    Hash: {res.get('hash')}")
            print("-" * 60)
            
        if len(risultati) > 20:
            print(f"... e altri {len(risultati)-20} risultati nascosti.")

if __name__ == "__main__":
    run_test()