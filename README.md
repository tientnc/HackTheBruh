# ↗ HackTheBruh

**Who will buy or sell next week?** Earlier wallet performance → later market participation.

[![Implemented explorer — illustrated overview, not a browser screenshot](docs/images/demo-overview.svg)](web/README.md)

**[Demo guide →](web/README.md)** · **[Browse data →](docs/data-catalog.md)** · **[Actual results →](analysis/participation/2026-01/v1/README.md)**

| 100 earlier markets | 20 later markets | Next 7 days | 100 candidate wallets |
| :---: | :---: | :---: | :---: |
| 2025 Finance | January 2026 Finance | Unique buyers / sellers | Earlier-only selection |

![Measured results and limitations](analysis/participation/2026-01/v1/results.svg)

**Provisional groups:** 1 stronger, 26 other, 73 unknown. Stronger-group predictions did not beat the baseline. The candidate set covers about 5% of observed participant-market pairs.

![Cloud data architecture](docs/images/cloud-architecture.svg)

**Deployment:** Supabase schema created; dataset upload and Vercel deployment pending. The local demo is labeled snapshot preview until connected.

<details><summary>Run locally</summary>

```powershell
node scripts/build-demo.mjs
node scripts/preview-demo.mjs
```

Open [localhost:4173](http://127.0.0.1:4173). Node 20+; no npm install.

</details>

<details><summary>Reproduce the research</summary>

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m polyresearch.participation
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

[Full experiment](analysis/participation/2026-01/v1/README.md) · [Wallet IDs](analysis/active-finance-wallets/README.md) · [Primary references](docs/research/wallet-skill.md)

</details>

**[Visual documentation hub →](docs/README.md)** · [Cloud setup](docs/deployment.md) · [Research target](docs/research/wallet-participation-target.md)
