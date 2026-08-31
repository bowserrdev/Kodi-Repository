#!/usr/bin/env python3
"""Sincronizza gli addon del repo nella cartella addon di Kodi, COPIANDO.

Sostituisce i symlink che c'erano in ~/Library/Application Support/Kodi/addons.
Perche' i symlink non vanno usati qui (incidente del 31/08/2026, 2098 file persi):
l'installer di Kodi, quando installa o aggiorna un addon, PRIMA cancella la cartella
di destinazione e POI scompatta lo zip. Se la destinazione e' un symlink al repo,
la cancellazione lo ATTRAVERSA e cancella i sorgenti veri. Si chiude cosi' un anello
vizioso: il repo produce lo zip, Kodi installa lo zip, l'installazione distrugge il
repo che l'ha prodotto.

C'e' un secondo danno, meno visibile e piu' insidioso: con quella struttura `git
status` marcava i file come CANCELLATI pur essendo su disco, quindi git non tracciava
piu' nulla di quello che ci si faceva dentro. Lavoro non committato e' rimasto
invisibile per giorni (la skin 3.3.11, il ramo resource:// di blur_service.py).

Con una copia, la cartella di Kodi diventa usa-e-getta: se Kodi la sovrascrive si
rilancia questo script e non si e' perso niente, e il repo torna a essere l'unica
fonte di verita' -- che e' il punto piu' importante.

Uso:
    python3 deploy_local.py              # anteprima, non tocca niente
    python3 deploy_local.py --apply      # esegue davvero
    python3 deploy_local.py --apply plugin.video.fenlight   # un solo addon
"""

import argparse
import os
import shutil
import subprocess
import sys
import unicodedata

# Le regole di esclusione NON si duplicano qui: sono gia' in generate_repo.py e devono
# restare una cosa sola, altrimenti prima o poi divergono e il deploy di sviluppo
# spedisce qualcosa che il pacchetto pubblicato non contiene (o viceversa).
from generate_repo import is_excluded

REPO = os.path.dirname(os.path.abspath(__file__))
KODI_ADDONS = os.path.expanduser('~/Library/Application Support/Kodi/addons')

# File che nascono dall'uso e non appartengono al sorgente. Vanno esclusi in ENTRAMBE
# le direzioni: non si copiano dal repo e non si cancellano dalla destinazione.
JUNK = ('.DS_Store', '.git', '.github', '.gitignore', '.gitattributes', '__pycache__')


def norm(relpath):
    """Chiave di confronto stabile fra i due lati.

    macOS scrive i nomi in NFD (la enne di 'Espana' come n + tilde combinante), mentre
    la copia dentro Kodi -- arrivata da uno zip -- li ha in NFC (un solo codepoint).
    Sono gli stessi file, ma come stringhe sono diversi: senza normalizzare, il confronto
    fra sorgente e destinazione classificava i sei 'media/flags/color/mpaa/Espana *.png'
    come 'presenti solo sulla destinazione' e il deploy li avrebbe CANCELLATI. Sono
    proprio quelli che generate_repo.KEEP tiene apposta, perche' dentro Textures.xbt
    hanno la enne codificata latin-1 e la skin li cerca in UTF-8, quindi a runtime
    ricade sul file su disco.
    """
    return unicodedata.normalize('NFC', relpath)


def is_junk(relpath):
    parts = relpath.replace(os.sep, '/').split('/')
    if any(p in JUNK for p in parts):
        return True
    name = parts[-1]
    return name.endswith('.pyc') or name.endswith('.zip') or name.endswith('.zip.md5')


def addon_ids():
    """Le cartelle del repo che sono davvero addon (hanno un addon.xml)."""
    out = []
    for item in sorted(os.listdir(REPO)):
        if item.startswith('.'):
            continue
        if os.path.isfile(os.path.join(REPO, item, 'addon.xml')):
            out.append(item)
    return out


def source_files(addon_id):
    """I file da spedire, filtrati esattamente come li filtra il pacchetto pubblicato."""
    root = os.path.join(REPO, addon_id)
    keep = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in JUNK and not d.startswith('.')]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            if is_junk(rel) or is_excluded(addon_id, rel):
                continue
            keep.add(norm(rel.replace(os.sep, '/')))
    return keep


def dest_files(addon_id):
    """Cosa c'e' gia' nella cartella di Kodi, al netto di quello che non ci riguarda."""
    root = os.path.join(KODI_ADDONS, addon_id)
    found = set()
    if not os.path.isdir(root):
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in JUNK]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, '/')
            # Un file ESCLUSO sulla destinazione non e' spazzatura da rimuovere: e'
            # roba del dispositivo. Il caso che conta e'
            # 1080i/script-skinvariables-generator-includes*.xml, che e' GENERATO da
            # Kodi e contiene la configurazione reale dei widget della home. Cancellarlo
            # (o sovrascriverlo col file di un'altra macchina) azzera la home.
            if is_junk(rel) or is_excluded(addon_id, rel):
                continue
            found.add(norm(rel))
    return found


def kodi_is_running():
    try:
        r = subprocess.run(['pgrep', '-x', 'Kodi'], capture_output=True, text=True)
        return r.returncode == 0
    except Exception:
        return False


def plan(addon_id):
    src, dst = source_files(addon_id), dest_files(addon_id)
    root_s, root_d = os.path.join(REPO, addon_id), os.path.join(KODI_ADDONS, addon_id)
    nuovi, aggiornati = [], []
    for rel in sorted(src):
        a, b = os.path.join(root_s, rel), os.path.join(root_d, rel)
        if not os.path.exists(b):
            nuovi.append(rel)
        else:
            sa, sb = os.stat(a), os.stat(b)
            # mtime al secondo: sotto c'e' rumore fra filesystem diversi (APFS conserva
            # i nanosecondi, la copia no) e si finirebbe per riscrivere tutto ogni volta.
            if sa.st_size != sb.st_size or int(sa.st_mtime) != int(sb.st_mtime):
                aggiornati.append(rel)
    rimossi = sorted(dst - src)
    return nuovi, aggiornati, rimossi


def apply(addon_id, nuovi, aggiornati, rimossi):
    root_s, root_d = os.path.join(REPO, addon_id), os.path.join(KODI_ADDONS, addon_id)
    for rel in nuovi + aggiornati:
        a, b = os.path.join(root_s, rel), os.path.join(root_d, rel)
        os.makedirs(os.path.dirname(b), exist_ok=True)
        shutil.copy2(a, b)          # copy2 conserva mtime, cosi' il giro dopo non ricopia
    for rel in rimossi:
        try:
            os.remove(os.path.join(root_d, rel))
        except OSError:
            pass
    # Cartelle rimaste vuote dopo le rimozioni
    for dirpath, dirnames, filenames in os.walk(root_d, topdown=False):
        if dirpath != root_d and not dirnames and not filenames:
            try:
                os.rmdir(dirpath)
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('addons', nargs='*', help='addon da sincronizzare (default: tutti)')
    ap.add_argument('--apply', action='store_true', help='esegue davvero (senza, e\' un\'anteprima)')
    args = ap.parse_args()

    if not os.path.isdir(KODI_ADDONS):
        sys.exit(f"Cartella addon di Kodi non trovata:\n  {KODI_ADDONS}")

    # Kodi tiene aperti i database degli addon e puo' riscrivere i file sotto di se':
    # sincronizzare mentre gira lascia uno stato misto e va scoperto molto piu' tardi.
    if args.apply and kodi_is_running():
        sys.exit("Kodi e' in esecuzione: chiudilo prima di sincronizzare.")

    targets = args.addons or addon_ids()
    sconosciuti = [a for a in targets if not os.path.isfile(os.path.join(REPO, a, 'addon.xml'))]
    if sconosciuti:
        sys.exit("Non sono addon di questo repo: " + ', '.join(sconosciuti))

    print(f"repo  {REPO}")
    print(f"kodi  {KODI_ADDONS}")
    print("MODALITA' ANTEPRIMA -- non viene toccato niente (usa --apply per eseguire)\n"
          if not args.apply else "")

    tot = [0, 0, 0]
    for addon_id in targets:
        nuovi, aggiornati, rimossi = plan(addon_id)
        if not (nuovi or aggiornati or rimossi):
            print(f"  {addon_id}: gia' allineato")
            continue
        print(f"  {addon_id}: {len(nuovi)} nuovi, {len(aggiornati)} aggiornati, {len(rimossi)} rimossi")
        for rel in (nuovi + aggiornati)[:8]:
            print(f"      -> {rel}")
        if len(nuovi) + len(aggiornati) > 8:
            print(f"      -> ... e altri {len(nuovi) + len(aggiornati) - 8}")
        for rel in rimossi[:8]:
            print(f"      x  {rel}")
        if len(rimossi) > 8:
            print(f"      x  ... e altri {len(rimossi) - 8}")
        if args.apply:
            apply(addon_id, nuovi, aggiornati, rimossi)
        tot[0] += len(nuovi); tot[1] += len(aggiornati); tot[2] += len(rimossi)

    print(f"\ntotale: {tot[0]} nuovi, {tot[1]} aggiornati, {tot[2]} rimossi"
          + ("" if args.apply else "  (nulla e' stato scritto)"))


if __name__ == '__main__':
    main()
