# -*- coding: utf-8 -*-
# SOTTOTITOLI AUTOMATICI -- lotto 420 (SOTTOTITOLI.md).
#
# Prima si scaricava da OpenSubtitles il sottotitolo piu' votato per il titolo, ignorando il file: spesso di un'altra
# edizione, a 25 fps, sfasato di secondi. Ora il file che si riproduce da' la temporizzazione giusta -- i tempi delle sue
# tracce di sottotitoli incorporate, in qualunque lingua, letti dai Cues del matroska -- e il sottotitolo nella lingua
# dell'utente ci si allinea sopra (modules/sottotitoli_sync.py). Si applica solo se l'allineamento ha agganciato il
# parlato: meglio nessun sottotitolo che uno sbagliato.
#
# Due tempi:
# - prepara(), dal player PRIMA di play(), in un thread suo: la rete gratuita. Hash del file, cache, Cues, ricerca.
#   Lavora mentre Kodi apre il file; se la sorgente non parte si e' spesa solo rete che non consuma quota.
# - auto_subtitle_check(), dopo onAVStarted come prima: audio gia' nella lingua, traccia completa nel file, cache, poi
#   download (quota) e allineamento, al piu' MAX_DOWNLOAD candidati. Una riga di log alla fine, piu' i rifiuti.
import os
from threading import Thread
from time import perf_counter
import xbmc
import xbmcvfs

from caches.settings_cache import get_setting
from modules.kodi_utils import sleep, notification, get_property, get_jsonrpc, jsonrpc_get_system_setting, logger

MAX_DOWNLOAD = 3            # per file: la regola dei buchi ne usa in media 1,14-1,26 (banco, 29/09)
MIN_BATTUTE = 50            # meno e' un forzato o un pezzo: il banco non li ha mai trattati come sottotitoli
ATTESA_PREPARAZIONE = 30    # s dopo onAVStarted; di solito la preparazione ha finito da un pezzo
CARTELLA = 'special://temp/fenlight_autosub/'
# ISO 639-2 bibliografico e terminologico: un mkv puo' dire "ger" o "deu" per la stessa lingua
_B_T = {'alb': 'sqi', 'arm': 'hye', 'baq': 'eus', 'bur': 'mya', 'chi': 'zho', 'cze': 'ces', 'dut': 'nld', 'fre': 'fra',
        'geo': 'kat', 'ger': 'deu', 'gre': 'ell', 'ice': 'isl', 'mac': 'mkd', 'may': 'msa', 'per': 'fas', 'rum': 'ron',
        'slo': 'slk', 'tib': 'bod', 'wel': 'cym'}


# SCELTA DELLA TRACCIA INTERNA (Lettore -> Lingua -> Lingua preferita per i sottotitoli).
# Toppa a valle di Kodi: VideoPlayer ordina i sottotitoli con PredicateSubtitlePriority, che a
# parita' di lingua non distingue il completo dal forzato e lascia vincere il flag "default"
# dell'mkv; con "Solo forzati" non lega la scelta alla lingua dell'audio. Qui si rifa' la
# scelta a flusso partito, leggendo isforced/isimpaired dal JSON-RPC (Kodi 20+), che
# xbmc.Player non espone. Annotata in PR.md.
_FORZATO_NEL_NOME = ('forced', 'forzat', 'forcé', 'forzad', 'erzwungen')
_NON_UDENTI_NEL_NOME = ('sdh', 'non udenti', 'hearing impaired')


def _iso3(valore):
    valore = (valore or '').strip()
    if not valore:
        return ''
    try:
        codice = xbmc.convertLanguage(valore, xbmc.ISO_639_2)
    except Exception:
        codice = ''
    return (codice or valore).lower()


def _forzato(traccia):
    nome = (traccia.get('name') or '').lower()
    return bool(traccia.get('isforced')) or any(t in nome for t in _FORZATO_NEL_NOME)


def _non_udenti(traccia):
    nome = (traccia.get('name') or '').lower()
    return bool(traccia.get('isimpaired')) or any(t in nome for t in _NON_UDENTI_NEL_NOME)


def _preferita(tracce):
    # A parita' di tipo: prima quella senza SDH, poi quella che l'mkv marca default, poi l'ordine.
    return min(tracce, key=lambda t: (_non_udenti(t), not t.get('isdefault'), t.get('index', 0)))


def _stato_flussi():
    try:
        return get_jsonrpc({'jsonrpc': '2.0', 'id': 1, 'method': 'Player.GetProperties',
                            'params': {'playerid': 1, 'properties': ['subtitles', 'currentsubtitle',
                                                                     'subtitleenabled', 'currentaudiostream']}})
    except Exception:
        return None


def _imposta_sottotitolo(indice, attivo=True):
    params = {'playerid': 1, 'subtitle': indice if attivo else 'off'}
    if attivo:
        params['enable'] = True
    try:
        get_jsonrpc({'jsonrpc': '2.0', 'id': 1, 'method': 'Player.SetSubtitle', 'params': params})
    except Exception:
        pass


def _applica_preferenza_kodi(stato):
    scelta = jsonrpc_get_system_setting('locale.subtitlelanguage', 'original')
    if scelta in ('original', 'none', '') or not stato:
        return
    tracce = [t for t in (stato.get('subtitles') or []) if 'index' in t]
    corrente = stato.get('currentsubtitle') or {}
    attivi = bool(stato.get('subtitleenabled'))

    if scelta == 'forced_only':
        audio = _iso3((stato.get('currentaudiostream') or {}).get('language'))
        if not audio or audio in ('und', 'unk'):
            return
        candidate = [t for t in tracce if _forzato(t) and _iso3(t.get('language')) == audio]
        if not candidate:
            # Nessun forzato nella lingua dell'audio: "solo forzati" vuol dire niente sottotitoli,
            # non il forzato di un'altra lingua che Kodi puo' aver acceso.
            if attivi:
                _imposta_sottotitolo(None, attivo=False)
                logger('FenLight SUB', 'solo forzati: nessuno per audio=%s, spenti' % audio)
            return
    else:
        lingua = _iso3(xbmc.getLanguage(xbmc.ISO_639_2)) if scelta == 'default' else _iso3(scelta)
        if not lingua:
            return
        candidate = [t for t in tracce if not _forzato(t) and _iso3(t.get('language')) == lingua]
        if not candidate:
            return  # nessun completo: resta la scelta di Kodi (eventualmente il forzato)

    traccia = _preferita(candidate)
    if attivi and corrente.get('index') == traccia['index']:
        return
    _imposta_sottotitolo(traccia['index'])
    logger('FenLight SUB', 'preferenza=%s -> traccia %s (%s, %s) al posto di %s'
           % (scelta, traccia['index'], traccia.get('language'), traccia.get('name') or '-',
              corrente.get('index') if attivi else 'spenti'))



# ---- lingua ---------------------------------------------------------------------------------------------------------
def _lingua_utente():
    """{'2': 'it', 'codici': {'it', 'ita'}, 'nome': 'italian'} della lingua scelta nelle impostazioni, o None."""
    from modules.settings import preferred_language
    pref = preferred_language()
    if not pref: return None
    try: pref_2 = (xbmc.convertLanguage(pref, xbmc.ISO_639_1) or '').lower()
    except Exception: pref_2 = ''
    if not pref_2: return None
    try: pref_3 = (xbmc.convertLanguage(pref, xbmc.ISO_639_2) or '').lower()
    except Exception: pref_3 = ''
    try: nome = (xbmc.convertLanguage(pref, xbmc.ENGLISH_NAME) or '').lower()
    except Exception: nome = ''
    codici = {c for c in (pref, pref_2, pref_3) if c}
    codici |= {t for b, t in _B_T.items() if b in codici} | {b for b, t in _B_T.items() if t in codici}
    return {'2': pref_2, 'codici': codici, 'nome': nome}


def _in_lingua(nomi, lingua):
    for s in nomi or []:
        sl = (s or '').lower().strip()
        if sl in lingua['codici'] or (lingua['nome'] and lingua['nome'] in sl): return True
    return False


def _traccia_per_kodi(stato, lingua):
    """La traccia NON forzata nella lingua fra quelle che Kodi elenca (senza SDH se c'e' la scelta), o None. Dove i
    Cues non dicono niente (mp4, mkv senza cue) e' anche il giudizio sulla presenza: li' non si contano le battute."""
    tracce = [t for t in (stato or {}).get('subtitles') or [] if 'index' in t and not _forzato(t) and _iso3(t.get('language')) in lingua['codici']]
    return _preferita(tracce) if tracce else None


def _accendi_traccia(lingua):
    """Accende la traccia completa nella lingua che il file ha gia'. Prima si lasciava a Kodi, ma Kodi la accende solo
    se nelle sue impostazioni i sottotitoli sono su quella lingua: V1 sul Mac (29/09), Noriko's Dinner Table con una
    traccia italiana di 1719 battute, niente download e niente sottotitoli a schermo. -> testo per il log."""
    stato = _stato_flussi()
    t = _traccia_per_kodi(stato, lingua)
    if not t: return ', Kodi non la elenca'
    corrente = (stato or {}).get('currentsubtitle') or {}
    if (stato or {}).get('subtitleenabled') and corrente.get('index') == t['index']: return ', gia\' accesa'
    _imposta_sottotitolo(t['index'])
    return ', accesa la traccia %s' % t['index']


# ---- prima di play() ------------------------------------------------------------------------------------------------
def prepara(player):
    """Dal player, prima di play(): fa partire la rete gratuita in sfondo. -> dizionario della preparazione, o None se i
    sottotitoli automatici sono spenti o incompleti nelle impostazioni. Tutto cio' che serve si legge ADESSO dal player:
    un cambio di sorgente dall'OSD lo riscrive."""
    try:
        if get_setting('fenlight.autosub.enabled') != 'true': return None
        from apis.opensubtitles_api import OpenSubtitlesAPI
        api, lingua = OpenSubtitlesAPI(), _lingua_utente()
        if not api.pronto() or not lingua: return None
        h = getattr(player, '_intestazione', None) or {}
        item = getattr(player, 'playing_item', None) or {}
        # Il titolo dai METADATI della sorgente (set_constants), non da player.imdb_id & co.: quelli li scrive
        # make_listing(), dentro self.play(), cioe' dopo questo punto. Letti da li' erano vuoti e la ricerca non partiva
        # (V1 sul Mac, 29/09: tre film, "0 risultati" in 0,0 s).
        meta = getattr(player, 'meta', None) or {}
        p = {'api': api, 'lingua': lingua, 'url_player': getattr(player, 'url', None), 'url': h.get('url') or getattr(player, 'url', None),
             'testa': h.get('testa'), 'dimensione': h.get('dimensione'), 'durata': h.get('durata'), 'info_hash': item.get('hash'),
             'imdb': meta.get('imdb_id') or '', 'tipo': meta.get('media_type') or 'movie',
             'stagione': meta.get('season') or '', 'episodio': meta.get('episode') or '', 'scatola': {}}
        p['thread'] = Thread(target=_prepara, args=(p,))
        p['thread'].daemon = True
        p['thread'].start()
        return p
    except Exception:
        return None


def _prepara(p):
    s = p['scatola']
    try:
        from modules import sottotitoli_rete
        from caches import sottotitoli_cache
        s['oshash'], s['hash_da'], s['hash_conto'] = sottotitoli_rete.hash_file(p['info_hash'], None, p['url'], p['dimensione'], p['testa'])
        s['chiave'] = s['oshash'] or ('%s:%s' % (p['info_hash'].lower(), p['dimensione']) if p['info_hash'] and p['dimensione'] else None)
        s['cache'] = sottotitoli_cache.leggi(s['chiave'], p['lingua']['2'])
        if s['cache'] and s['cache'].get('srt'): return          # ripresa: niente Cues, niente ricerca
        s['struttura'] = sottotitoli_rete.struttura(p['url'], p['testa'], p['dimensione'], p['lingua']['codici'])
        if s['struttura'].get('utente'): return                  # c'e' gia' nel file, completa: la sceglie Kodi
        t0 = perf_counter()
        if p['tipo'] == 'episode':
            s['risultati'] = p['api'].cerca([p['lingua']['2']], serie_imdb=p['imdb'], stagione=p['stagione'], episodio=p['episodio'],
                                            moviehash=s['oshash']) if p['imdb'] and p['stagione'] and p['episodio'] else []
        else:
            s['risultati'] = p['api'].cerca([p['lingua']['2']], imdb_id=p['imdb'], moviehash=s['oshash'])
        s['ms_ricerca'] = int((perf_counter() - t0) * 1000)
    except Exception as e:
        s['errore'] = type(e).__name__


# ---- dopo onAVStarted -----------------------------------------------------------------------------------------------
def auto_subtitle_check(player):
    timeout = 0
    while not getattr(player, '_av_started', False) and timeout < 150:
        sleep(300)
        timeout += 1
    if not player.isPlayingVideo():
        return

    stato = _stato_flussi()
    _applica_preferenza_kodi(stato)

    p = getattr(player, '_sottotitoli', None) or prepara(player)
    if not p:
        return
    try: _sottotitoli(player, p, stato)
    except Exception as e: logger('FenLight SUB', 'errore %s' % type(e).__name__)


def _n(x, d=2):
    x = round(x or 0, d) or 0.0            # niente "-0,00": i tempi allineati sono decimali, un buco puo' valere -1e-12
    return ('%.*f' % (d, x)).replace('.', ',')
def _secondi(ms): return '%s s' % _n((ms or 0) / 1000.0, 1)


def _descrivi(c):
    return '%s %s %d' % (c.get('lingua') or '?', 'testo' if not c.get('classe') else 'immagine', len(c.get('linea') or ()))


def _applica(player, p, testo):
    """Scrive il sottotitolo e lo accende, se si sta ancora riproducendo lo stesso file (un cambio di sorgente dall'OSD
    riusa lo stesso player con un altro url)."""
    if not player.isPlayingVideo() or getattr(player, 'url', None) != p['url_player']: return False
    cartella = xbmcvfs.translatePath(CARTELLA)
    if not xbmcvfs.exists(cartella): xbmcvfs.mkdirs(cartella)
    percorso = os.path.join(cartella, 'autosub.%s.srt' % p['lingua']['2'])
    with open(percorso, 'wb') as f: f.write(testo.encode('utf-8'))
    player.setSubtitles(percorso)
    player.showSubtitles(True)
    return True


def _scarica(api, file_id, costo):
    """(battute [(inizio, fine, testo)] o None, motivo). Consuma quota."""
    from modules import sottotitoli_sync as S
    t0 = perf_counter()
    dati, restanti, motivo = api.scarica(file_id)
    costo['download'] += int((perf_counter() - t0) * 1000)
    costo['scaricati'] += 1
    if restanti is not None: costo['restanti'] = restanti
    if motivo == 'quota finita': notification('Auto Subtitles: daily download limit reached', 4000)
    if not dati: return None, motivo
    return S.leggi_srt(S.decodifica(dati)), None


def _sottotitoli(player, p, stato):
    from modules import sottotitoli_sync as S, sottotitoli_tracce as T
    from caches import sottotitoli_cache
    from apis.opensubtitles_api import candidati, QUOTA_PROP
    lingua = p['lingua']

    # 1. audio gia' nella lingua dell'utente: niente, come prima
    audio = []
    for _ in range(10):
        audio = player.getAvailableAudioStreams()
        if audio: break
        sleep(500)
    if audio and _in_lingua(audio, lingua):
        # una riga anche qui: una riproduzione senza riga non si distingue da una in cui il flusso non e' partito
        return logger('FenLight SUB', 'audio gia\' in %s (%s): niente' % (lingua['2'], ', '.join(audio)))

    p['thread'].join(ATTESA_PREPARAZIONE)
    if p['thread'].is_alive():
        return logger('FenLight SUB', 'preparazione oltre %d s: niente' % ATTESA_PREPARAZIONE)
    s = p['scatola']
    st = s.get('struttura') or {}
    rete = []
    if s.get('hash_da'):
        c = s.get('hash_conto') or {}
        rete.append('hash %s%s' % (s['hash_da'], ' %d req %s' % (c.get('richieste', 0), _secondi(c.get('ms'))) if c.get('richieste') else ''))
    if st:
        rete.append('cues %d req %d KB %s' % (st.get('richieste', 0), (st.get('byte') or 0) // 1024, _secondi(st.get('ms'))))
    if 'ms_ricerca' in s: rete.append('ricerca %s' % _secondi(s['ms_ricerca']))
    if s.get('errore'): rete.append('preparazione: errore %s' % s['errore'])

    # 2. traccia completa nella lingua dentro il file (contata dai Cues, non dal nome o dal flag): la sceglie Kodi
    if st.get('utente'):
        return logger('FenLight SUB', ' | '.join(['traccia completa nel file: %s, niente download%s' % (_descrivi(st['utente']), _accendi_traccia(lingua))] + rete))
    # 3. ripresa: il sottotitolo gia' allineato per questo file
    cache = s.get('cache')
    if cache and cache.get('srt'):
        e = cache.get('esito') or {}
        esito = 'dalla cache: %s %s' % (cache.get('file_id'), e.get('metodo') or '')
        if not _applica(player, p, cache['srt']): esito += ', non applicato (riproduzione cambiata)'
        return logger('FenLight SUB', ' | '.join([esito] + rete))
    # 4. dove i Cues non dicono niente, il giudizio di Kodi sulle tracce, senza i forzati
    if not st.get('cues') and _traccia_per_kodi(stato, lingua):
        return logger('FenLight SUB', ' | '.join(['traccia nella lingua nel file (flag di Kodi), niente download%s' % _accendi_traccia(lingua)] + rete))

    rifiutati = set((cache or {}).get('rifiutati') or ())
    cand = [(fid, a) for fid, a in candidati(s.get('risultati'), lingua['2']) if fid not in rifiutati]
    if not cand:
        return logger('FenLight SUB', ' | '.join(['nessun candidato (%d risultati, %d gia\' rifiutati)' % (len(s.get('risultati') or []), len(rifiutati))] + rete))
    if get_property(QUOTA_PROP) == 'finita':
        return logger('FenLight SUB', ' | '.join(['quota finita: niente download'] + rete))

    rif = st.get('rif') or []
    durata = (p['durata'] or 0) * 1000 or None
    costo = {'download': 0, 'allineamento': 0, 'scaricati': 0, 'restanti': None}
    rifiuti = []

    # 5a. senza riferimento: il primo candidato NON allineato, come prima (il ripiego per hash e' del lotto 421)
    if not rif:
        fid = cand[0][0]
        righe, motivo = _scarica(p['api'], fid, costo)
        if not righe:
            testo = 'senza riferimento (%s): %s non scaricato, %s' % (st.get('motivo') or 'nessuna struttura', fid, motivo or 'vuoto')
        else:
            srt = S.scrivi_srt(righe, [(a, b, i) for i, (a, b, t) in enumerate(righe)])
            sottotitoli_cache.scrivi(s.get('chiave'), lingua['2'], fid, srt, {'metodo': 'non allineato'}, rifiutati)
            testo = 'senza riferimento (%s): %s applicato non allineato' % (st.get('motivo') or 'nessuna struttura', fid)
            if not _applica(player, p, srt): testo += ', non applicato (riproduzione cambiata)'
        return logger('FenLight SUB', ' | '.join([testo, 'download %s' % _secondi(costo['download'])] + rete))

    # 5b. candidati in ordine: download -> allineamento -> accettazione; regola dei buchi
    primo, riserva = rif[0]['linea'], (T.secondo(rif) or {}).get('linea')
    migliore = None
    for fid, a in cand:
        if costo['scaricati'] >= MAX_DOWNLOAD: break
        righe, motivo = _scarica(p['api'], fid, costo)
        if righe is None:
            rifiuti.append('%s non scaricato: %s' % (fid, motivo))
            if motivo == 'quota finita': break
            continue
        if len(righe) < MIN_BATTUTE:
            rifiutati.add(fid)
            rifiuti.append('%s rifiutato: %d battute' % (fid, len(righe)))
            continue
        t0 = perf_counter()
        e = S.con_riserva(primo, riserva, [(x[0], x[1]) for x in righe], durata)
        ok = S.accettabile(e)
        if ok: e['buchi'] = S.buchi(e['ref'], e['al'])
        costo['allineamento'] += int((perf_counter() - t0) * 1000)
        if not ok:
            rifiutati.add(fid)
            rifiuti.append('%s rifiutato cop %s prec %s' % (fid, _n(e['cop']), _n(e['precisione'])))
            continue
        if migliore is None or e['buchi'] < migliore[1]['buchi']: migliore = (fid, e, righe)
        if e['buchi'] <= S.SOGLIA_BUCHI: break
        rifiuti.append('%s accettabile ma buchi %s: si prova il successivo' % (fid, _n(e['buchi'])))

    testa = ['riferimento %s' % _descrivi(rif[0]), 'candidati %d, scaricati %d' % (len(cand), costo['scaricati'])]
    if migliore:
        fid, e, righe = migliore
        srt = S.scrivi_srt(righe, e['al'])
        sottotitoli_cache.scrivi(s.get('chiave'), lingua['2'], fid, srt,
                                 {'metodo': e['metodo'], 'cop': round(e['cop'], 3), 'prec': round(e['precisione'], 3),
                                  'buchi': round(e['buchi'], 3), 'rapporto': e['rapporto'], 'offset': int(e['offset'])}, rifiutati)
        metodo = e['metodo'] + (' %d tagli %d tolte' % (e['tagli'], e['tolte']) if e['metodo'] == 'tratti' else '')
        testo = '%s accettato: %s r %s off %+d cop %s prec %s buchi %s%s' % (
            fid, metodo, _n(e['rapporto'], 4), int(e['offset']), _n(e['cop']), _n(e['precisione']), _n(e['buchi']),
            ' (secondo riferimento %s)' % _descrivi(T.secondo(rif)) if e['rif'] == 1 else '')
        if not _applica(player, p, srt): testo += ', non applicato (riproduzione cambiata)'
        testa.append(testo)
    else:
        sottotitoli_cache.scrivi(s.get('chiave'), lingua['2'], None, None, {}, rifiutati)
        testa.append('nessun candidato accettato')
    testa += rete + ['download %s' % _secondi(costo['download']), 'allineamento %s' % _secondi(costo['allineamento'])]
    if costo['restanti'] is not None: testa.append('quota restante %s' % costo['restanti'])
    logger('FenLight SUB', ' | '.join(testa))
    for r in rifiuti: logger('FenLight SUB', r)
