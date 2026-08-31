# -*- coding: utf-8 -*-
# Tetto sulle invocazioni Python che caricano moduli nello stesso momento.
#
# PERCHE'. Kodi esegue ogni script come SOTTO-INTERPRETE dentro il proprio processo, e Python 3.11
# condivide UN SOLO GIL fra sotto-interpreti (il GIL per-interprete e' PEP 684, da 3.12 e su
# richiesta esplicita). Caricare moduli e' bytecode Python puro: tiene il GIL e non lo rilascia.
# Quindi N invocazioni che importano insieme non vanno su N core, si mettono in coda -- pagando in
# piu' il costo di contendersi il testimone.
#
# Misurato il 31/08-01/09/2026 sulle sole invocazioni che importano gli stessi 56 moduli:
#
#   interpreti     Mi Stick (4x A53)   se serializzasse      Mac M5 (10 core)   se serializzasse
#       1                618 ms              --                    11 ms              --
#       2                844 ms           1 237 ms                 28 ms            22 ms
#       3              2 584 ms           1 855 ms                 45 ms            33 ms
#
# A tre interpreti il costo supera la serializzazione pura su ENTRAMBE le macchine. Su dieci core.
# Non e' quindi un adattamento al ribasso per la stick: e' lavoro che non rende su nessun hardware.
# A due invece un guadagno reale c'e' ancora (844 contro 1 237 attesi): e' l'I/O che rilascia il GIL.
# Da qui SLOTS = 2, che e' il massimo con sovrapposizione utile misurata.
#
# COSA copre e cosa NO. Il cancello si tiene solo durante `import` + `import pigri`, cioe' fino a
# mark_phase('indexer_in'), e si rilascia PRIMA del lavoro dell'indexer. Sulla stick all'avvio sono
# 692 + 2 376 = 3 068 ms sotto cancello contro 766 ms di indexer lasciati liberi. La distinzione e'
# voluta e non va tolta: durante l'indexer c'e' la RETE, dove il GIL viene rilasciato davvero e il
# parallelismo funziona. Serializzare anche quello sarebbe una perdita netta.
#
# MECCANISMO. Serve un primitivo che attraversi i sotto-interpreti: hanno sys.modules separati,
# quindi un semaforo a livello di modulo non sarebbe condiviso, e os.environ e' una copia per
# interprete. Un file creato con O_CREAT|O_EXCL e' atomico su qualunque filesystem POSIX (FUSE
# compreso) ed e' visibile a tutti. Solo libreria standard: `os` e `time` sono gia' in sys.modules
# quando questo modulo viene letto, quindi il cancello non aggiunge un solo import all'albero.
#
# In caso di QUALUNQUE problema si passa senza aspettare. Un widget che non si costruisce e' un
# difetto visibile; un widget costruito piu' lentamente e' quello che succede oggi.
import os
import time

SLOTS = 2
# Oltre questa attesa si passa comunque. Serve a garantire che il cancello non possa MAI essere la
# ragione per cui un widget non compare: oltre il limite si degrada al comportamento di oggi, non si
# rompe niente. Tarato sotto il no_build_timeout=20s del paginatore, che e' il primo a lamentarsi.
MAX_WAIT = 8.0
# Uno slot piu' vecchio di cosi' e' di un'invocazione morta (crash, kill di Kodi) e va riciclato.
# Sopra il caso peggiore osservato per la sola fase di import sulla stick (3,6 s) con largo margine.
STALE = 25.0
POLL = 0.05

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.gate')
_held = []      # percorso dello slot posseduto, se ne abbiamo uno
_waited = [0.0]  # quanto abbiamo atteso, per la riga di log


def _claim(path):
    """Prova a prendere lo slot. O_EXCL e' la parte atomica: o lo crea questo, o nessun altro."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, str(time.time()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except Exception:
        return None        # il filesystem non collabora: il chiamante passa senza cancello


def _reap(path):
    """Ricicla uno slot lasciato da un'invocazione morta."""
    try:
        if time.time() - os.stat(path).st_mtime > STALE:
            os.unlink(path)
    except Exception:
        pass


def acquire():
    if _held:
        return
    try:
        os.makedirs(_DIR, exist_ok=True)
    except Exception:
        return
    t0 = time.time()
    while True:
        for i in range(SLOTS):
            path = os.path.join(_DIR, 'slot%d' % i)
            got = _claim(path)
            if got is None:
                return          # errore del filesystem: si passa, senza cancello
            if got:
                _held.append(path)
                _waited[0] = time.time() - t0
                return
        for i in range(SLOTS):
            _reap(os.path.join(_DIR, 'slot%d' % i))
        if time.time() - t0 >= MAX_WAIT:
            _waited[0] = time.time() - t0
            return              # si passa comunque: meglio lenti che fermi
        # time.sleep RILASCIA il GIL: chi aspetta qui non rallenta chi sta lavorando.
        time.sleep(POLL)


def release():
    """Idempotente: la chiamano sia mark_phase('indexer_in') sia la coda dell'invocazione."""
    while _held:
        try:
            os.unlink(_held.pop())
        except Exception:
            pass


def waited_ms():
    return _waited[0] * 1000.0
