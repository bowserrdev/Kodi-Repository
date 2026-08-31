import os
import glob
import hashlib
import zipfile
import re
import xml.etree.ElementTree as ET
from fnmatch import fnmatch

# File che vivono nella cartella dell'addon ma NON devono finire nel pacchetto pubblicato.
# Percorsi relativi alla radice dell'addon; una voce che finisce con '/' esclude l'intera cartella,
# le altre sono glob. Motivazioni:
#  - extras/screenshots, extras/nodes: zero riferimenti nel codice della skin e nessuno <screenshot>
#    dichiarato in addon.xml, quindi sono peso morto (11 file, 4,85 MB).
#  - script-skinvariables-generator-includes*: e' un file GENERATO sul dispositivo e contiene la
#    configurazione reale dei widget della home (guid, list_id mdblist, label). Il .gitignore della
#    skin lo esclude gia', ma questo script cammina il filesystem e non git: spedirlo significa
#    sovrascrivere la home di ogni dispositivo con quella della macchina che ha generato lo zip.
EXCLUDE = {
    'skin.arctic.fuse.3': (
        'extras/screenshots/',
        'extras/nodes/',
        '1080i/script-skinvariables-generator-includes*.xml',
        '1080i/script-skinvariables-skinusers.xml',
        '1080i/script-skinshortcuts-includes.xml',
        'media/',
    ),
}

# Eccezioni che VINCONO su EXCLUDE. Servono per media/: i file sciolti sono i sorgenti da cui e'
# stato compilato media/Textures.xbt (verificato 2026-08-31: 1382 dei 1390 sono dentro il bundle),
# quindi a runtime sono ridondanti e non vanno spediti -- ma restano nel repo perche' servono a
# ricompilare il bundle. Le eccezioni sono gli 8 file che il bundle NON copre:
#  - common/menu1.png e menu2.png: assenti dal bundle e usati 4 volte in Includes_Search.xml;
#  - i sei 'espana *.png': dentro il bundle ma con la enne codificata latin-1, mentre la skin li
#    cerca in UTF-8, quindi la ricerca nel bundle fallisce e Kodi ricade sul file su disco.
KEEP = {
    'skin.arctic.fuse.3': (
        'media/Textures.xbt',
        'media/common/menu1.png',
        'media/common/menu2.png',
        'media/flags/color/mpaa/espa*.png',
    ),
}

def _matches(rules, relpath):
    # Confronto insensibile al maiuscolo: i nomi reali su disco non sempre sono quelli che ci si
    # aspetta (es. 'Espana X.png' con la maiuscola) e fnmatch e' case-sensitive su POSIX.
    low = relpath.lower()
    for rule in rules:
        rule = rule.lower()
        if rule.endswith('/'):
            if low.startswith(rule): return True
        elif fnmatch(low, rule): return True
    return False

def is_excluded(addon_id, relpath):
    relpath = relpath.replace(os.sep, '/')
    if _matches(KEEP.get(addon_id, ()), relpath): return False
    return _matches(EXCLUDE.get(addon_id, ()), relpath)

def create_zip(addon_id, version):
    zip_name = f"{addon_id}-{version}.zip"
    zip_path = os.path.join(addon_id, zip_name)
    
    # Rimuove vecchi zip (e i relativi .md5) presenti nella cartella dell'addon
    for f in glob.glob(os.path.join(addon_id, "*.zip")) + glob.glob(os.path.join(addon_id, "*.zip.md5")):
        try:
            os.remove(f)
        except OSError:
            pass
            
    print(f"Compressione di {addon_id} (v{version})...")
    skipped = []
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(addon_id):
            # Esclude file di sistema e file zip nidificati
            files = [f for f in files if not f.endswith('.zip') and not f.startswith('.')]
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for file in files:
                file_path = os.path.join(root, file)
                if is_excluded(addon_id, os.path.relpath(file_path, addon_id)):
                    skipped.append(os.path.relpath(file_path, addon_id))
                    continue
                arcname = os.path.relpath(file_path, os.path.dirname(addon_id))
                zipf.write(file_path, arcname)

    if skipped:
        print(f"  esclusi dal pacchetto: {len(skipped)} file")

    # Hash di integrita' accanto allo zip: Kodi lo scarica come <zip>.md5 e
    # rifiuta il pacchetto se il download e' troncato o corrotto.
    digest = hashlib.md5()
    with open(zip_path, 'rb') as zf:
        for chunk in iter(lambda: zf.read(1024 * 1024), b''):
            digest.update(chunk)
    with open(zip_path + '.md5', 'w', encoding='utf-8') as hf:
        hf.write(digest.hexdigest())
    print(f"  {zip_name}.md5 = {digest.hexdigest()}")

def generate_repo():
    addons_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n'
    
    for item in os.listdir('.'):
        if os.path.isdir(item) and not item.startswith('.'):
            addon_xml_path = os.path.join(item, 'addon.xml')
            if os.path.exists(addon_xml_path):
                try:
                    tree = ET.parse(addon_xml_path)
                    root = tree.getroot()
                    addon_id = root.attrib['id']
                    version = root.attrib['version']
                    
                    with open(addon_xml_path, 'r', encoding='utf-8') as f:
                        xml_content = f.read()
                        # Rimuove l'intestazione xml per unire i contenuti
                        xml_content = re.sub(r'<\?xml.*?\?>', '', xml_content).strip()
                        addons_xml += xml_content + "\n"
                    
                    create_zip(addon_id, version)
                except Exception as e:
                    print(f"Errore nell'elaborazione di {item}: {e}")
                    
    addons_xml += "</addons>\n"
    
    # Scrittura del file addons.xml principale
    with open('addons.xml', 'w', encoding='utf-8') as f:
        f.write(addons_xml)
    print("addons.xml generato con successo.")
    
    # Generazione dell'hash MD5 per notificare Kodi delle variazioni
    md5 = hashlib.md5(addons_xml.encode('utf-8')).hexdigest()
    with open('addons.xml.md5', 'w', encoding='utf-8') as f:
        f.write(md5)
    print("addons.xml.md5 generato con successo.")

if __name__ == "__main__":
    generate_repo()