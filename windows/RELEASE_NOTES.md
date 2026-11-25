## EMELab 0.1.2 BETA TEST per Windows / for Windows

**Installazione / Installation:** `EMELab-Setup-0.1.2.exe` (senza diritti di amministratore / no admin rights) oppure / or `EMELab-0.1.2-portable.zip` → `EMELab.bat`. Controllo del file scaricato / check the download: `SHA256SUMS.txt`.

### 🇮🇹 Novità
- **🆕 Avviso di nuova versione** come in FeedLab: all'avvio il programma chiede a GitHub se c'è una versione più nuova e mostra le novità. C'è anche il pulsante «🔄 Controlla aggiornamenti» nella barra laterale.
- **🏠 Stazione:**
  - il locator aggiorna subito latitudine e longitudine (prima restavano a 0);
  - posizione esatta da Google Maps: clic destro sulla parabola, copia le coordinate e incollale (va bene anche il link); il programma calcola il locator preciso a 10 caratteri;
  - piccola mappa del mondo con la tua stazione e le stazioni EME dell'elenco, con zoom;
  - pulsante «🌡️ Prova la stazione meteo» per controllare subito l'indirizzo della tua stazione meteo personale.
- **⚡ Potenza:** per ogni banda scegli se hai un SSPA o un TWT e quale dispositivo (catalogo con i più comuni, per esempio Qorvo QPA1010 a 10 GHz e Siemens RW1136 modificato a 24 GHz); i suoi dati riempiono il calcolo e la scelta resta salvata.
- **Import ADIF:** entrano solo i QSO EME da 10 GHz in su; gli altri vengono contati e lasciati fuori.

### 🇬🇧 What's new
- **🆕 New-version notice** as in FeedLab: at start the program asks GitHub whether a newer version exists and shows what's new. There is also a «🔄 Check for updates» button in the sidebar.
- **🏠 Station:**
  - the locator now updates latitude and longitude at once (they used to stay at 0);
  - exact position from Google Maps: right-click on the dish, copy the coordinates and paste them (the link works too); the program works out the precise 10-character locator;
  - small world map with your station and the EME stations of the directory, with zoom;
  - «🌡️ Test the weather station» button to check the address of your personal weather station at once.
- **⚡ Power:** for each band choose whether you have an SSPA or a TWT and which device (catalogue of the common ones, e.g. Qorvo QPA1010 at 10 GHz and a modified Siemens RW1136 at 24 GHz); its data fill the calculation and the choice is saved.
- **ADIF import:** only EME QSOs from 10 GHz up are taken; the others are counted and left out.

## EMELab 0.1.1 BETA TEST per Windows / for Windows

**Installazione / Installation:** `EMELab-Setup-0.1.1.exe` (senza diritti di amministratore / no admin rights) oppure / or `EMELab-0.1.1-portable.zip` → `EMELab.bat`. Controllo del file scaricato / check the download: `SHA256SUMS.txt`.

### 🇮🇹 Novità
- **Interfaccia in italiano e in inglese:** si sceglie nella barra laterale.
- **📻 Collegamento con WSJT-X** (protocollo UDP):
  - riceve frequenza, modo e decodifiche;
  - registra nel Log QSO ogni QSO che confermi in WSJT-X, con tutte le condizioni di quel momento (Luna ai due capi, distanze, Doppler, spread, atmosfera, meteo);
  - colora in WSJT-X chi ti manca e chi hai già collegato;
  - imposta il sottomodo Q65 consigliato in base al mutual spread con il DX.
- **📜 Storico della stazione:** parabola, potenza e ricevitore per ogni banda e periodo. Il segnale atteso e la correzione appresa dai QSO usano il periodo giusto per ogni QSO, con la tabella della correzione periodo per periodo.
- **🎯 Puntamento:**
  - scansione del Sole (a croce o a deriva) adattata con il modello disco ⊗ fascio: larghezza del fascio vera, errore di puntamento e fattore Y, salvati nel diario;
  - modello di puntamento: zero AZ ed EL, inclinazione dell'asse, flessione, con il residuo rispetto a HPBW/10.
- **EA3HMJ Tracking Software Suite (DriverDish):**
  - importa le scansioni a deriva (DriftScan) e la mappa delle correzioni (corrections.txt);
  - legge posizione, offset e stato dell'antenna dal server telnet di DriverDish, solo in lettura.
- **Polarizzazione:** sfasamento spaziale (Dpol) e convenzione H/V per regione (orizzontale in Nord America, verticale altrove), modificabile per ogni stazione.

### 🇬🇧 What's new
- **Italian and English interface:** chosen in the sidebar.
- **📻 WSJT-X link** (UDP protocol):
  - receives frequency, mode and decodes;
  - logs every QSO you accept in WSJT-X with all the conditions of that moment (Moon at both ends, distances, Doppler, spread, atmosphere, weather);
  - colours in WSJT-X the stations you still need and the ones already worked;
  - sets the Q65 submode recommended for the mutual spread with the DX.
- **📜 Station history:** dish, power and receiver for each band and period. The expected signal and the correction learned from the QSOs use the right period for each QSO, with a table of the correction period by period.
- **🎯 Pointing:**
  - sun scan (cross or drift) fitted with the disc ⊗ beam model: true beamwidth, pointing error and Y-factor, saved in the diary;
  - pointing model: AZ and EL zero, axis tilt, sag, with the residual compared with HPBW/10.
- **EA3HMJ Tracking Software Suite (DriverDish):**
  - imports the drift scans (DriftScan) and the correction map (corrections.txt);
  - reads the dish position, offsets and status from DriverDish's telnet server, read-only.
- **Polarisation:** spatial offset (Dpol) and H/V convention by region (horizontal in North America, vertical elsewhere), editable for each station.

Requisiti / Requirements: Windows 10/11 64-bit.

---

## EMELab 0.1.0 BETA TEST per Windows / for Windows

**Installazione / Installation:** `EMELab-Setup-0.1.0.exe` (senza diritti di amministratore / no admin rights) oppure / or `EMELab-0.1.0-portable.zip` → `EMELab.bat`. Controllo del file scaricato / check the download: `SHA256SUMS.txt`.

### 🇮🇹 Prima versione di prova
EMELab è il laboratorio di misure, pianificazione e log EME da 10 a 134 GHz, compagno di FeedLab ma programma a sé. In questa versione l'interfaccia è solo in italiano.
- **🧭 Assistente all'avvio:** data e ora UTC, meteo da te, posizione e distanza della Luna, spread. Poi ti chiede che cosa vuoi fare: pianificare un QSO, migliorare la catena o il setup, capire i tuoi risultati.
- **Pianificazione:** il tuo orizzonte libero, le finestre di Luna con meteo, spread, distanza e Sole, la classifica di chi puoi collegare con la probabilità tecnica, lo sfasamento di polarizzazione (Dpol) e il testo dello sked.
- **Segnale atteso:** equazione radar bistatica con la distanza reale della Luna, i fasci delle due stazioni sulla Luna, l'atmosfera ai due capi e le soglie Q65 contro lo spread. Il modello si corregge con i rapporti dei tuoi QSO.
- **Log QSO:** registra ogni condizione del collegamento, importa ed esporta in ADIF per gli altri logger e stampa le etichette QSL.
- **Stazioni EME** da WSJT-X (CALL3.TXT, ALL.TXT) e dalla EME Directory di PA0PLY; QRZ.com con il tuo account, che resta sul tuo PC.
- **Misure:** diario delle misure (sole, Luna, terra, fuoco), analisi (G/T, efficienza, NF, puntamento) e stampa in PDF; flusso solare del giorno da NOAA con l'avviso sui brillamenti.
- **📈 Grafici e interpolazioni:** qualsiasi parametro dei QSO o delle misure contro qualsiasi altro.
- **Catena:** schede Puntamento, LNA, SSPA (con il dimensionamento del dissipatore), TWT e Progettazione, con il catalogo dei dispositivi a 10, 24 e 47 GHz e la lettura dei datasheet.
- **File di progetto di FeedLab:** EMELab legge parabola e feed senza ricalcolarli.
- **Schede a scelta:** mostri solo quelle che ti servono.
- Tutti i tuoi dati restano sul tuo PC.

### 🇬🇧 First test version
EMELab is the EME measurement, planning and log laboratory from 10 to 134 GHz, a companion of FeedLab but a program of its own. In this version the interface is in Italian only; English will follow.

Requisiti / Requirements: Windows 10/11 64-bit.
