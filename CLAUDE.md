# EMELab: regole di lavoro / working rules

## Rilascio ogni 5 modifiche / Release every 5 changes

Come in FeedLab: ogni **5 modifiche** entrate in `main` dall'ultimo tag si esce con una nuova versione.
Same rule as FeedLab: after every **5 changes** merged to `main` since the last tag, release a new version.

Contare le modifiche / count the changes:

```
git log --oneline $(git describe --tags --abbrev=0)..origin/main
```

Alla quinta modifica / at the fifth change:

1. `emelab/__init__.py`: alzare `__version__` (patch +1, es. 0.1.2 → 0.1.3).
2. `windows/RELEASE_NOTES.md`: nuova sezione in cima con i titoli `### 🇮🇹 Novità` e `### 🇬🇧 What's new`.
   L'avviso di nuova versione nell'app (`emelab/updates.py`) legge proprio queste sezioni.
3. Tag `vX.Y.Z` e release su GitHub: la build Windows parte dal tag (`.github/workflows/windows.yml`).

Senza una release più nuova su GitHub l'avviso «🆕 Nuova versione disponibile» non compare agli utenti.
Without a newer GitHub release users never see the «🆕 New version available» notice.
