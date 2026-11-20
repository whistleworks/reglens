# ADR-0004 — Qdrant embedded (local mode) as dev backend and future fallback

- **Stato:** accettato
- **Data:** 2026-11-20

## Contesto
- In ADR-0001 il dev locale prevedeva Qdrant in Docker (`docker-compose.yml`, immagine `qdrant/qdrant:v1.20.0`).
- Sulla macchina di sviluppo Docker e Homebrew non sono installati, e serviva comunque indicizzare ed eseguire gli eval.
- Il brief prevede già, in M5, un fallback `INDEX_MODE=local_snapshot` con l'indice incluso nell'immagine.

## Decisione
- `QDRANT_URL` accetta due forme:
  - `http(s)://...`: un server Qdrant (Docker in dev o Qdrant Cloud in prod);
  - `path:<dir>`: Qdrant **embedded** in-process, persistito su disco (`qdrant_client.QdrantClient(path=...)`), per esempio `QDRANT_URL=path:qdrant_local`.
- Il codice di indicizzazione e di ricerca è lo stesso per entrambe le forme: solo `make_client` in `src/reglens/retrieval/qdrant.py` cambia.

## Alternative scartate
- **Aspettare Docker:** bloccava tutta la M1 e la M2.
- **Chroma o FAISS per il dev:** avremmo un backend diverso da quello di produzione e due implementazioni da mantenere.
- **Binario Qdrant nativo:** richiede comunque un'installazione manuale; la modalità embedded non richiede nulla.

## Conseguenze
- **Limiti della modalità embedded:**
  - un solo processo alla volta può aprire la stessa cartella: indicizzazione ed eval non possono girare in parallelo sullo stesso path;
  - gli indici di payload non hanno effetto: i filtri funzionano, ma con scansione;
  - le prestazioni non sono rappresentative del server.
- **Latenze:** quelle misurate in questa modalità sono latenze di sviluppo, da non riportare come latenze di produzione.
- **Da rifare con il server:** l'integration test (`make test-integration`) e il sanity check BEIR vanno rieseguiti su un server Qdrant prima del deploy (M5).
- **Base del fallback di M5:** la stessa modalità è il fondamento di `INDEX_MODE=local_snapshot`.
