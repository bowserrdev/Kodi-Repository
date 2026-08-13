# Rimozione riferimenti TMDbHelper dalla skin

Registro delle funzionalità disattivate durante la pulizia dei riferimenti morti a
`plugin.video.themoviedb.helper`. Serve come specifica di ciò che l'helper addon dovrà
ricostruire, senza doverlo ricavare dal `git log`.

**Nessuna delle voci qui elencate era funzionante al momento della rimozione**: le proprietà
che le pilotavano erano popolate dal servizio ListItemMonitor di TMDbHelper, assente in questa
installazione. Le condizioni erano quindi permanentemente false.

## Metodo

Due esiti possibili per ogni variabile, mai una cancellazione cieca:

- **Eliminata** — nessun consumatore in tutto l'albero della skin, né statico né dinamico.
- **Collassata sul fallback** — la variabile ha un `<value>` finale incondizionato ed è ancora
  raggiungibile. Poiché la proprietà pilota è sempre vuota, oggi ricade *sempre* su quel
  fallback: mantenerlo solo lui produce output identico byte per byte.

### Attenzione ai riferimenti dinamici

Un controllo dei consumatori basato solo su `$VAR[Nome]` letterale **non è sufficiente**.
[Includes_Info.xml](skin.arctic.fuse.3/1080i/Includes_Info.xml) costruisce nomi di variabile a
runtime:

```xml
<param name="label">$VAR[Label_$PARAM[service]_Status]$VAR[Label_$PARAM[service]_StatusDate, ,]</param>
<param name="icon">$VAR[Image_$PARAM[service]_Status]</param>
```

con `service` ∈ {`ListItem`, `Player`}. Sei nomi risultano quindi orfani a una ricerca testuale
pur essendo vivi. Prima di eliminare una variabile va sempre verificata anche l'espansione dei
`$VAR[...$PARAM...]`.

---

## Lotto 1 — Stato serie/film (`ListItem.Status`, `Player.Status`)

Proprietà TMDbHelper coinvolte: `ListItem.Status`, `Player.Status`, `ListItem.Next_Aired*`,
`ListItem.Last_Aired*`, `Player.Next_Aired`, `Player.Last_Aired`, `ListItem.Premiered*`,
`Player.Premiered`, `ListItem.Birthday`, `ListItem.Monitor.TMDb_Type`, `ListItem.base_dbtype`,
`Player.base_dbtype`.

Riferimenti morti rimossi: **113**.

### Eliminate (orfane)

| Variabile | File | Cosa mostrava |
|---|---|---|
| `Image_DialogInfo_Status` | Includes_Images.xml | icona calendario per lo stato, nella scheda info |
| `Label_ListItem_NextAired_Header` | Includes_Labels.xml | intestazione "Prossimo episodio" / "Ultimo andato in onda" / "Prima TV" |
| `Label_ListItem_NextAired` | Includes_Labels.xml | data estesa del prossimo/ultimo episodio |
| `Label_Overlay_Premiered` | Includes_Labels.xml | riga data nell'overlay; unico consumatore delle due precedenti, a sua volta orfano |

### Collassate sul fallback (raggiunte dinamicamente da Includes_Info.xml)

| Variabile | Valore mantenuto | Cosa mostrava prima |
|---|---|---|
| `Image_ListItem_Status` | `flags/$VAR[Color_Directory]/status/calendar-day.png` | icona diversa per Returning/Ended/Canceled/Released/Planned |
| `Image_Player_Status` | `flags/$VAR[Color_Directory]/status/calendar-day.png` | come sopra, per il media in riproduzione |
| `Label_ListItem_Status` | `$LOCALIZE[13205]` (Sconosciuto) | "In corso" / "Terminata" / "Cancellata" / "In produzione" / "Prevista", più le varianti "Nuova stagione"/"Nuovo episodio" basate su Next_Aired |
| `Label_Player_Status` | `$LOCALIZE[13205]` (Sconosciuto) | come sopra, per il media in riproduzione |
| `Label_ListItem_StatusDate` | `$LOCALIZE[1446]` (Sconosciuto) | data del prossimo/ultimo episodio, o data di uscita per i film |
| `Label_Player_StatusDate` | `$LOCALIZE[1446]` (Sconosciuto) | come sopra, per il media in riproduzione |

### Da ricostruire nell'helper

Una sola proprietà per lo stato, più le date di messa in onda:

- `Status` — valori attesi dalla skin: `Returning Series`, `Ended`, `Canceled`, `Released`,
  `In Production`, `Post Production`, `Planned`
- `Next_Aired`, `Next_Aired.Long`, `Next_Aired.Season`, `Next_Aired.Episode`,
  `Next_Aired.Days_Until_Aired`
- `Last_Aired`, `Last_Aired.Long`, `Last_Aired.Days_From_Aired`
- `Premiered`, `Premiered_Long`

TMDb le espone tutte su `/tv/{id}` (`status`, `next_episode_to_air`, `last_episode_to_air`) e
`/movie/{id}` (`status`, `release_date`), quindi bastano le chiamate che l'helper farà comunque.

**Nota:** la riga "Stato" nel pannello info è emessa solo con l'impostazione skin
`TMDbHelper.EnableData` attiva ([Includes_Info.xml:254](skin.arctic.fuse.3/1080i/Includes_Info.xml#L254)).
Con quella attiva, oggi mostra in permanenza "Sconosciuto" più l'icona calendario: era così
anche prima di questa pulizia.

---

## Lotto 2 — Variabili ibride (crew, studio, lingua, path parametriche)

Variabili che contengono **sia** una riga FenLight viva **sia** righe TMDbHelper morte. A
differenza del lotto 1 qui non si eliminano variabili: si rimuovono singole righe `<value>` e la
variabile resta viva e funzionante.

Riferimenti morti rimossi: **153** su 45 righe, in 9 variabili.

### Perché è neutro

La condizione di ogni riga rimossa interroga solo proprietà che nessuno scrive, quindi non può
mai essere vera. Una riga che non può mai corrispondere non contribuisce al risultato **a
prescindere dalla sua posizione** nella variabile.

Prima di procedere sono state cercate le due forme di riga che *non* sarebbero state neutre:

- **condizione mista** (`!String.IsEmpty(FenLight.X) + String.IsEqual(TMDbHelper.Y,z)`);
- **condizione viva ma valore morto** — la riga corrisponde, restituisce vuoto e blocca le righe
  successive; rimuoverla farebbe emergere una riga sottostante.

Zero occorrenze di entrambe. Una guardia nello script fallisce se una riga da rimuovere contiene
un riferimento TMDbHelper *vivo*.

| Variabile | File | Righe tolte | Cosa resta |
|---|---|---|---|
| `Label_FromDirector` | Includes_Labels.xml | 10 | riga FenLight + fallback nativo `ListItem.Director` |
| `Label_FromWriter` | Includes_Labels.xml | 10 | idem, su `ListItem.Writer` |
| `Label_FromStudio` | Includes_Labels.xml | 6 | riga FenLight + fallback |
| `Label_Language` | Includes_Labels.xml | 1 | riga FenLight + fallback |
| `Image_OSD_WriterIcon` | Includes_Images.xml | 5 | thumb FenLight |
| `Image_DirectorIcon` | Includes_Images.xml | 5 | thumb FenLight |
| `Path_Param_Query` | Includes_Paths.xml | 2 | 7 righe FenLight |
| `Path_Param_Type` | Includes_Paths.xml | 2 | 3 righe FenLight |
| `Path_VideoInfo_Trailers` | Includes_Paths.xml | 4 | solo il ramo musicvideo (YouTube) |

### Attenzione: `Null.xsp` non è sempre la scelta giusta

Nel fix OSD le path svuotate hanno ricevuto il fallback `Null.xsp`, perché alimentano dei
container. `Path_VideoInfo_Trailers` **no**, ed è deliberato: uno dei suoi consumatori è
`SetProperty(PlayTrailerItems,...)`, e quella proprietà viene testata per vuoto —
[Custom_1122_Dialog_SelectTrailer.xml:6](skin.arctic.fuse.3/1080i/Custom_1122_Dialog_SelectTrailer.xml#L6)
chiude il dialog se è vuota. Con `Null.xsp` la proprietà risulterebbe valorizzata e il selettore
trailer mostrerebbe una lista vuota invece di chiudersi.

Regola: `Null.xsp` per i `<content>` dei container, stringa vuota per le proprietà su cui la skin
fa `String.IsEmpty`.

### Da ricostruire nell'helper

Nulla di nuovo: crew, studio e lingua sono già coperti da FenLight tramite `skin_properties.py`.
Restano da ripristinare i **trailer** per film e serie (`/movie/{id}/videos`, `/tv/{id}/videos`),
oggi limitati ai musicvideo.

---

## Lotto 3 — Reparto crew nella scheda plot (`Label_Overlay_*`)

Riferimenti morti rimossi: **203**.

### La struttura trovata

`Label_Overlay_PlotBox` (consumata da `Dialog_DialogPlot.xml`) è un **aggregatore**: una singola
riga incondizionata che concatena 16 frammenti nella forma `$VAR[nome,prefisso,suffisso]`. In
quella forma Kodi emette il prefisso — l'intestazione di sezione, es. "Fotografia" — **solo se la
variabile non è vuota**. Le variabili crew erano tutte vuote, quindi né i nomi né le intestazioni
comparivano già prima.

Serviva perciò chirurgia a tre livelli diversi, non uno solo:

1. **frammento** — dall'aggregatore sono stati tolti i 10 frammenti morti (bracket matching, sono
   annidati), lasciando i 6 vivi;
2. **variabile** — le 9 variabili rimaste senza consumatori sono state eliminate;
3. **riga** — sulle 6 ibride superstiti sono state tolte solo le righe morte.

| Eliminate | Ridotte alla sola riga viva |
|---|---|
| `Label_Overlay_Production`, `_Sound`, `_ArtDepartment`, `_Cinematography`, `_Editing`, `_AwardsWon`, `_AwardsNominated`, `_Providers`, `_FileDetails`, `Label_Plot_Episode_Type_TMDBHelper` | `Label_Overlay_Directing`, `_Writing`, `_TopCast`, `_Tagline`, `_Critics`, `Label_Plot_TMDbHelper` |

Le ridotte conservano il ramo nativo `!$EXP[Exp_TMDbHelper_IsData]` → `$INFO[ListItem.Director]`,
`ListItem.Plot`, ecc. `Label_Overlay_Title` è rimasta intatta: la sua seconda riga usa
`base_label`, che è viva (la scrive il blur service).

### Due grafie per la stessa proprietà

Nel codice convivono **`TMDbHelper.`** (987 occorrenze) e **`TMDBHelper.`** (40). Le window
property di Kodi sono case-insensitive, quindi sono la stessa proprietà: `TMDBHelper.ListItem.base_plot`
è morta esattamente come `TMDbHelper.ListItem.base_plot`, e `TMDBHelper.WidgetContainer` è viva
esattamente come `TMDbHelper.WidgetContainer`.

I classificatori dei lotti 2 e 3 erano inizialmente case-sensitive. L'effetto è **sotto-rimozione,
mai sovra-rimozione** — una riga viene tolta solo se un riferimento morto viene trovato — ma il
rilevamento del *vivo* dev'essere case-insensitive con la stessa cura, altrimenti il rischio si
inverte. Le variabili del lotto 2 sono state ricontrollate: nessun residuo.

**Da qui in avanti ogni pattern usa `TMD[Bb]Helper\.`**

### Non incluso

`Includes_Overlay.xml` (22 rif. morti) usa proprietà di natura diversa — `IsUpdatingRatings`,
`IsUpdatingDetails`, `IsUpdating`, `Instance`, `Position`, `CurrentWindow` — che governano lo
stato dell'overlay, non le etichette. Merita un lotto proprio.

### Da ricostruire nell'helper

Le sezioni della scheda plot oggi assenti: **Produzione**, **Suono**, **Reparto artistico**,
**Fotografia**, **Montaggio**, **Premi** (vinti e nomination), **Provider streaming**, **dettagli
file**. Fonti TMDb: `/movie/{id}/credits` e `/tv/{id}/credits` con raggruppamento per
`department`, più `/watch/providers`. I premi non sono su TMDb: servono OMDb o MDBList.

---

## Lotto 4 — Cluster scheda info (DialogInfo + le sue path)

Riferimenti morti rimossi: **107**. Primo lotto **non invisibile**, approvato esplicitamente.

### Perché qui la rimozione si vede

Nei lotti 1-3 il codice morto non veniva mai disegnato. Qui no: `_Widget_Row`
([Includes_Widgets.xml:101](skin.arctic.fuse.3/1080i/Includes_Widgets.xml#L101)) rende visibile una
riga se `altvisible` è vero **anche a container vuoto**, e i pannelli morti avevano
`altvisible = CurrentID != BaseID` (vero quando la riga non è a fuoco) o addirittura `true` fisso.
Comparivano quindi come righe con la sola intestazione e nulla sotto.

### Pannelli rimossi (11)

Sceneggiatore, Creatore, Starring primo attore, Starring secondo attore, Stagioni ed Episodi
(3 varianti), Commenti, più i 3 pannelli del contesto persona (film con, serie con, troupe in
comune). Restano 14 pannelli, tutti alimentati da FenLight o dalla libreria locale.

Il pannello **Regista** è stato conservato: il suo `<content>` è già FenLight.

### Tre path che facevano davvero scattare il prompt

Il discriminante è se `$INFO[X,prefisso,]` ha `X` valorizzata — solo allora il prefisso `plugin://`
viene emesso:

| Dove | X | Azione |
|---|---|---|
| folderpath del regista | `Path_FromDirector` **viva** (FenLight) | riscritto su FenLight, allineato al `<content>` sottostante |
| galleria immagini persona | `ListItem.UniqueID(tmdb)` **viva** | `Null.xsp` |
| folderpath parametrico | proprietà morta, mai emesso | rimosso |

### Variabili di Includes_Paths

Eliminate perché orfane: `Path_VideoOSD_TMDbQuery`, `Path_VideoInfo_OnlineFlatSeasons`,
`Path_VideoInfo_OnlineComments`.

Ridotte, applicando la regola del lotto 2:

- `Path_VideoInfo_OnlineFanart` → `Null.xsp` (alimenta un `<content>`);
- `Path_FromWriter`, `Path_InfoParams_TMDbType/TMDbID/Season/Episode` → `<value />` vuoto
  (alimentano `SetProperty`/`param`, non container).

### Nota sullo strumento di verifica

L'invariante dei vivi è scesa da 266 a 265 senza che si fosse persa alcuna funzionalità: il
tokenizer dell'inventario tronca `TMDbHelper.ListItem.$PARAM[type].$PARAM[item].TMDb_ID` a
`ListItem.`, che per prefisso combacia con `base_label`/`base_poster` e veniva quindi contato come
vivo. Quella forma è invece **sempre morta**: il nome si compone a runtime da proprietà che nessuno
scrive. Lo script è stato corretto; la superficie viva reale è **258 rif. / 29 proprietà**.

---

## Lotto 5 — Crew, studio e valutazioni (Images + Labels)

Riferimenti morti rimossi: **291**, su 99 righe in 31 variabili. Il lotto più grande dell'intera
operazione. `Includes_Labels.xml` è sceso a **zero** riferimenti morti, `Includes_Images.xml` a 3.

Stessa forma del lotto 2 — riga viva più righe con condizione irraggiungibile — e il classificatore
ha confermato **99 righe di tipo A, zero miste, zero della forma pericolosa** (condizione viva con
valore morto). Nessuna sorpresa in esecuzione.

### Ridotte alla sola riga viva

`Label_Studio`, `Label_Country`, `Label_Genre`, `Label_Director`, `Label_Writer`, `Label_Creator`,
`Label_OSD_FromDirector`, `Label_OSD_FromWriter`, `Label_OSD_DirectorName`, `Label_OSD_WriterName`,
`Label_OSD_StudioName`, `Image_Clearlogo_Title`, `Image_Overlay_Poster`, `Image_OSD_Clearart`,
`Image_OSD_Clearlogo`, `Image_PVRPoster`, `Image_PVREpgLandscapeArt`, `Image_CombinedStudio`, più le
quattro varianti `*_RottenTomatoes*`.

### Eliminate perché orfane

`Image_OSD_CombinedStudio`, `Image_FromWriter`, `Image_OSD_DirectorIcon`, `Image_CreatorIcon`,
`Image_OSD_CreatorIcon`, `Image_OSD_StudioIcon`, `Label_FromCreator`.

### Svuotate perché ancora consumate

`Image_FromDirector` (alimenta un `<icon>`) e `Image_WriterIcon` (param `shot`): entrambe alimentano
un'immagine, non un container, quindi ricevono `<value />` e **non** `Null.xsp` — regola del lotto 2.

### Da ricostruire nell'helper

- **Crew nell'OSD durante la riproduzione**: nomi e ritratti di regista, sceneggiatore, creatore,
  studio (`Player.Director.*`, `Player.Writer.*`, `Player.Studio.*`, `Player.Network.*`).
  Fonte: `/movie/{id}/credits`, `/tv/{id}/credits`.
- **Valutazioni Rotten Tomatoes**, icona critica e icona pubblico, sia per l'elemento selezionato
  sia per quello in riproduzione. Non sono su TMDb: servono OMDb o MDBList.
- **Icone studio/network combinate**.

---

## Lotto 6a — Scheda info: sezione crew e righe permanentemente nascoste

Riferimenti morti rimossi: **27** (114 → 87). `Includes_DialogInfo.xml` è sceso da 35 a 8.

### Due forme di `<visible>`, trattate in modo opposto

- **OR con un'alternativa viva** (`FenLight… | TMDbHelper… | ListItem…`): il termine morto è sempre
  falso e in un OR non contribuisce, quindi si toglie solo quello. 7 condizioni ripulite.
- **Dipendente solo da proprietà morte**: il controllo è *permanentemente nascosto*. Qui togliere la
  `<visible>` lo farebbe **comparire**: va rimosso il controllo intero. Così per Provider, Incassi/
  Budget, Premi, Tagline e il pulsante Trakt.

### Rimossi

Sezione **Crew Lists** completa (8 widget × 10 voci: Regista, Sceneggiatore, Produzione, Suono,
Reparto artistico, Fotografia, Montaggio, Creatore) — qui `altvisible` era **morto**, a differenza
del lotto 4, quindi la sezione non disegnava nulla e la rimozione è neutra.

Righe metadati permanentemente nascoste: Provider streaming, Incassi/Budget, Premi, Tagline.

Pulsante **Trakt** del menu video: nascosto da `TMDbHelper.TraktIsAuth` e comunque inerte, perché il
suo `onclick` è `$VAR[Action_Sync]`, interamente `RunScript(plugin.video.themoviedb.helper,…)`.

### Lasciati di proposito

I due `<param name="croplogo">Window(Home).Property(TMDbHelper.ListItem.Current.CropImage)</param>`.
Il valore viene sostituito **testualmente** dentro `String.IsEmpty($PARAM[croplogo])`
([Includes_Info.xml:393](skin.arctic.fuse.3/1080i/Includes_Info.xml#L393)): rimuovere il param
produrrebbe `String.IsEmpty()` senza argomento, che è peggio del riferimento morto. Vanno tolti
quando l'helper ripopolerà `CropImage`.

### Due errori commessi, entrambi intercettati dalle verifiche

**1. Blocco sbagliato rimosso.** Per isolare il controllo da eliminare cercavo «l'`<include content=>`
più vicino sopra il marcatore». Ma `TraktIsAuth` sta dentro una *definizione* `<include name=>`, non
dentro un `<include content=>`: la ricerca ha agganciato un blocco estraneo e ha cancellato l'azione
«riproduci trailer» di un pulsante video — che era **viva** (`<param name="trailer">ListItem.Trailer`).
Ripristinata dal blob git, senza il solo `trailer_fallback` morto.

**2. Definizioni cancellate come orfane pur non essendolo.** Kodi ammette **due sintassi** di
riferimento a un include: `<include content="Nome">` e `<include>Nome</include>`. Il controllo
cercava solo la prima, così `DialogInfo_Widget_Grouplist` (usato da `DialogVideoInfo.xml` e
`DialogMusicInfo.xml` con la seconda forma) e `DialogInfo_CrewItems` (usato da `Dialog_DialogView.xml`)
risultavano orfani. Tutte e tre le definizioni sono state ripristinate.

**Da qui in avanti il controllo di orfanità cerca entrambe le sintassi e ignora i commenti.**

Nota: `DialogPlotFake`, `Hub_Disabled_Onload`, `Settings_InfoText`, `View_Furniture_Scrollbar_V`
risultano usati ma non definiti — è così **da prima** di questo lavoro, non è una regressione.

---

## Fuori lotto — rimozione della funzione "riproduci trailer"

Richiesta dall'utente: funzione mai usata. Non è codice morto ma **funzionalità viva rimossa per
scelta**, quindi va in una categoria a sé rispetto ai lotti.

È un sottosistema autonomo, e rimuovere solo il pulsante avrebbe lasciato tre finestre orfane.

### File eliminati

`Custom_1122_Dialog_SelectTrailer.xml`, `Custom_1123_Dialog_Trailer.xml`, `Dialog_DialogTrailer.xml`,
`shortcuts/builtins/skinvariables-playtrailer.json` (192 righe in totale).

Rimossa anche la riga `<include file="Dialog_DialogTrailer.xml" />` da `Includes.xml`: senza quella,
Kodi avrebbe cercato un file inesistente.

### Definizioni e riferimenti rimossi

`Action_PlayTrailer_OnClick`, `DialogInfo_VideoButtons_Trailer` (+2 referenze), `DialogCustom_Trailers`,
`DialogCustom_Trailers_Content`, `Path_VideoInfo_Trailers`, `Image_Trailer_PlayPause`,
`Label_Trailer_PlayPause`, la voce "riproduci trailer" del menu contestuale (già nascosta), il
pannello **Videos** della scheda info e il `SetProperty(trailer,…,1114)` rimasto inerte.

### Residuo innocuo

`Window.IsVisible(1123)` compare ancora in `Includes_Background.xml`, `Includes_Defaults.xml` e
`Includes_Expressions.xml` come guardia sulla finestra video. Con la finestra 1123 inesistente la
condizione è sempre falsa, quindi le guardie diventano no-op: è il comportamento corretto in assenza
del dialog trailer. Lasciate perché toccare `Includes_Background.xml` significherebbe rimettere mano
al layer del blur senza alcun guadagno.

### Nota sull'invariante

La superficie viva è scesa da 258 a 256 perché due riferimenti a `TMDbHelper.ContextMenu` vivevano
dentro i file trailer eliminati. Non è una regressione: sparisce la funzione che li usava. Verificato
che il meccanismo resti coerente — 12 scritture e 12 letture della proprietà.

---

## Fuori lotto — prompt "installa TMDbHelper" nell'OSD video

Anticipato rispetto al piano perché era un disturbo attivo durante la riproduzione, non codice
morto silenzioso.

**Meccanismo:** i bottoni dell'OSD aprono finestre di supporto al solo `onfocus`, non al click.
[VideoOSD.xml:75](skin.arctic.fuse.3/1080i/VideoOSD.xml#L75), bottone "salta avanti":

```xml
<onfocus condition="!VideoPlayer.Content(livetv)">ActivateWindow(1143)</onfocus>
```

La finestra 1143 carica un container il cui path era `plugin://plugin.video.themoviedb.helper/`.
Con l'addon assente, Kodi apre il prompt di installazione. Bastava passare sul bottone.

**Correzione:** rimossi i soli valori `themoviedb.helper`, aggiunto il fallback
`special://skin/extras/playlists/Null.xsp`. I valori nativi sono stati conservati.

| Variabile / file | Valori tolti | Conservato |
|---|---|---|
| `Path_OSD_NextRecommendation` | 3 | `playlistvideo://` — il "prossimo episodio" dalla playlist, che funziona nativamente |
| `Path_OSD_Cast` | 3 | nessuno: era interamente TMDbHelper |
| `Path_OSD_Episodes` | 1 | `playlistvideo://` e `videodb://` |
| `Custom_1193_VideoOSDInfo.xml` | 1 | il ramo `VideoOSD.InfoDialog.Path`, punto di aggancio per l'helper |

### Da ricostruire nell'helper

- **Raccomandazione successiva** (fine film): TMDb `/movie/{id}/recommendations`.
- **Cast nell'OSD**: `/movie/{id}/credits`, `/tv/{id}/credits`.
- **Elenco episodi nell'OSD** quando non c'è playlist: `/tv/{id}/season/{n}`.
- **Scheda info dal player**: va popolata `Window(Home).Property(VideoOSD.InfoDialog.Path)`;
  il ramo che la consuma è già in piedi in `Custom_1193_VideoOSDInfo.xml`.

### Residuo noto

`Custom_1114_Dialog_CustomPlot.xml` conserva un path TMDbHelper, ma è raggiungibile solo dal
dialog info (non durante la riproduzione) ed è dentro un `$INFO[Window.Property(tmdb_id),...]`,
che non emette nulla se la proprietà è vuota. Va trattato insieme al resto di
`Includes_DialogInfo.xml`.

---

## Lotto 6b — chiusura: impostazioni scrittura-sola, overlay di debug, ContextMenu

Il lotto che chiude la caccia ai riferimenti morti. La novità metodologica è che qui la
distinzione "vivo / morto" non si decide più guardando le proprietà di finestra, ma
**contando letture e scritture di ogni impostazione skin**.

### Il criterio: chi legge, non chi scrive

Molte impostazioni si chiamano `TMDbHelper.*` ma sono *impostazioni della skin*, scritte
dalla skin stessa con `Skin.SetBool` / `Skin.SetString`. Il nome non dice nulla sul fatto
che siano vive. Quello che conta è se **qualcuno le legge**:

| Impostazione | Letture | Verdetto |
|---|---|---|
| `EnableData` | `Exp_TMDbHelper_IsData`, usata 52 volte | **viva** |
| `EnableBlur` | `Exp_TMDbHelper_IsBlur` (27 usi) + `blur_service.py:162` | **viva** |
| `EnableCrop` | `Exp_TMDbHelper_IsCrop` (8 usi) | **viva** |
| `Blur.Size`, `Blur.Radius` | `blur_service.py:18-20` | **vive** |
| `DisableRatings` | nessuna (37 scritture) | morta |
| `Service` | solo la regola che riscrive `EnableData` | morta (anello chiuso) |
| `UseLocalWidgetContainer`, `DisableExtendedProperties`, `EnableCurrentWindowImages`, `DirectCallAuto`, `MonitorContainer`, `DisableArtwork`, `Corner.Radius`, `UseLocalWindowIDs` | nessuna | morte |
| `DisablePVR` | solo il proprio `<selected>` | morta (interruttore su sé stesso) |

Le prime cinque restano e vanno solo rinominate al punto 6. Le altre sono sparite.

### Rimossi

| File | Cosa | Perché |
|---|---|---|
| `Includes_Actions.xml` | `Action_RatingsMonitor` (42 righe) | 37 condizioni valutate a ogni ingresso in Home per scrivere un booleano che nessuno legge |
| `Includes_Actions.xml` | `Action_Sync` (10 righe) | variabile mai referenziata; tutti i valori chiamavano `RunScript(themoviedb.helper)` |
| `Includes_Actions.xml` | ponte `EnableData` → `Service` | l'altra metà dell'anello |
| `Home.xml`, `SkinSettings.xml` | le due chiamate a `Action_RatingsMonitor` | |
| `Home.xml` | `Corner.Radius`, `UseLocalWindowIDs` | |
| `skinvariables-startup.json` | 7 `Skin.Set*` + la regola `Service` | giravano **a ogni avvio** |
| `Includes_Overlay.xml` | 2 label di debug + `Overlay_IsUpdating`, `_Overlay_IsUpdating`, `Overlay_WidgetContainer` | overlay diagnostico su stato del servizio TMDbHelper |
| `Includes_Info.xml` | blocchi *Status* e *Awards* | entrambi gated su proprietà mai scritte: mai visibili |
| `Includes_Images.xml`, `Includes_Labels.xml` | le 6 variabili `*_Status` / `*_StatusDate` | diventate orfane con il blocco Status (vedi sotto) |
| `Dialog_DialogPVRInfo.xml` | bottone info | `<visible>` su `Monitor.TMDb_ID`: mai mostrato |
| `Includes_SkinSettings.xml` | radiobutton "TMDbHelper for PVR" | interruttore senza alcun effetto |
| 12 finestre | `SetProperty(TMDbHelper.ContextMenu,True)` | vedi sotto |

### Le variabili del lotto 1, finalmente eliminabili

Nel lotto 1 avevo cancellato per errore `Label_$PARAM[service]_Status` e compagne, raggiunte
dinamicamente da `Includes_Info.xml:255`, e avevo dovuto ripristinarle collassate sul loro
fallback. Rimosso ora il blocco *Status* che le consumava, sono diventate orfane per davvero
e sono uscite tutte e sei. L'ordine giusto era questo: **prima il consumatore, poi la variabile.**

### Una correzione: `TMDbHelper.ContextMenu`

Nel lotto precedente avevo dichiarato questa proprietà "bilanciata, 12 scritture e 12 letture".
Era sbagliato: avevo contato due volte le scritture. Il conto reale è **12 scritture e nessuna
lettura**, né nella skin né in Fen Light. Era il segnale con cui la skin diceva a TMDbHelper di
sospendere il monitoraggio mentre un dialog era aperto. Rimosse tutte e 12.

### Lasciati di proposito

- **`croplogo`** (5 punti: `Includes_Info`, `Includes_DialogInfo` ×2, `Includes_OSD` ×2).
  `CropImage` non è mai scritta, quindi il ramo "logo ritagliato" non è mai visibile e i
  7 rami alternativi si comportano già come oggi. È il gancio naturale per l'helper.
- **`Custom_1141_OSD_Cast.xml`**: il parametro `text` è stato svuotato invece che rimosso.
  L'include `OSD_Info_Tray` ha come default `$INFO[VideoPlayer.Plot]`: togliere il parametro
  avrebbe mostrato la trama del film sotto il nome di un attore.

### Trovato e non toccato: la scheda crew è irraggiungibile

`Custom_1120_Dialog_SelectCrew.xml` (finestra 1120) è alimentata da
`TMDbHelper.ListItem.<ruolo>.<n>.Name/Role/Thumb/TMDb_ID`, che nessuno scrive. In più
**nessuno attiva mai la finestra 1120**: gli unici riferimenti, in `Includes_DialogInfo.xml:1196`
e `:1210`, fanno `SetProperty(type,Director,1120)` senza `ActivateWindow`. Con `EnableData`
attivo — cioè sempre — il bottone *Regista* nella scheda info **non fa nulla al clic**.

Non è una rimozione di riferimenti morti ma una decisione di funzionalità, quindi è rimasta
in sospeso. Le due strade:

1. **Eliminare**: via finestra 1120, `DialogViewCrew_*`, `DialogInfo_CrewItem(s)`, e i bottoni
   Regista/Sceneggiatore usano il ramo `!IsData` che già funziona (`SendClick(13)`).
2. **Ricostruire su Fen Light**: `skin_properties.py` pubblica già
   `FenLight.ListItem.{Director,Writer}.{1..3}.{Name,TMDb_ID,Thumb}` — basterebbe riscrivere
   `DialogInfo_CrewItem` su quelle proprietà e aggiungere l'`ActivateWindow(1120)` mancante.
   Restano fuori Producer, Photography e Sound_Department, che Fen Light non pubblica.

### Conteggio

Riferimenti morti: **129 → 6** (i soli della scheda crew, in sospeso). Tutto il resto di ciò
che il classificatore segnala è per scelta: 30 impostazioni skin vive da rinominare al punto 6,
5 ganci `croplogo`, 1 commento.

`WidgetContainer` resta a 31 scritture / 91 letture, intatto.
