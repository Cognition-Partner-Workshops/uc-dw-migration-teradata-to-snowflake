# TD Migration Studio

Teradata → Azure Synapse / Google BigQuery / Amazon Redshift migration web app.
**Work in progress** — see [CONTRACTS.md](CONTRACTS.md) for the architecture contract. Full README lands with the integration PR.

```bash
make demo        # == docker compose up --build -d ; UI http://localhost:3000, API http://localhost:8000/docs
```

Dataset: [Olist Brazilian E-Commerce](https://github.com/olist/work-at-olist-data) (MIT, see `data/olist/LICENSE`).
