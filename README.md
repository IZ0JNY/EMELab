# EME Assistant

**Misure, analisi, pianificazione e log EME da 10 a 134 GHz** — il compagno di [FeedLab](https://github.com/IZ0JNY/FeedLab).
Software progettato da Ivan De Cesaris IZ0JNY · GPL-3.0-or-later.

EME Assistant usa i progetti di parabola e feed di FeedLab (file `.feedlab.json`), registra misure e QSO con tutte le condizioni del
momento (Sole e Luna da ERFA/IAU, atmosfera ITU-R P.676, librazione, spread e Doppler mutui, meteo), li confronta con la
teoria e **si tara sulla tua stazione** man mano che misuri.

- Stazione e configurazioni (parabola + feed + LNA + transverter + SSPA), progetti FeedLab
- Diario delle misure: rumore di Sole e Luna, cielo freddo, terra, carico caldo, scansioni del Sole, messa a fuoco
- Log EME con import/export ADIF, mappe, distanza a terra e percorso EME, etichette QSL
- Database delle stazioni EME (WSJT-X CALL3.TXT e ALL.TXT, EME Directory di PA0PLY, QRZ.com)
- Pianificatore: finestre comuni, spread mutuo, degradazione, perigeo, umidità prevista
- Analisi scientifica: G/T, efficienza, NF, superficie, modello di puntamento, con incertezze
- Stampe PDF, database SQLite locale consultabile

Tutti i dati restano sul tuo PC. Avvio:  `pip install -r requirements.txt`  poi  `streamlit run emelab_main.py`.

Fonti e ringraziamenti: vedi [docs/fonti.md](docs/fonti.md) e la scheda Credits.
