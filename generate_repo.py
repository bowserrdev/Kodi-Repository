import os
import glob
import hashlib
import zipfile
import re
import xml.etree.ElementTree as ET

def create_zip(addon_id, version):
    zip_name = f"{addon_id}-{version}.zip"
    zip_path = os.path.join(addon_id, zip_name)
    
    # Rimuove vecchi zip presenti nella cartella dell'addon
    for f in glob.glob(os.path.join(addon_id, "*.zip")):
        try:
            os.remove(f)
        except OSError:
            pass
            
    print(f"Compressione di {addon_id} (v{version})...")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(addon_id):
            # Esclude file di sistema e file zip nidificati
            files = [f for f in files if not f.endswith('.zip') and not f.startswith('.')]
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(addon_id))
                zipf.write(file_path, arcname)

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