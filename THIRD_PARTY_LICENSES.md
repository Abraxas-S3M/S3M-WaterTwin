# Third-Party Licenses

All runtime and development dependencies are pinned to exact versions (see
`pyproject.toml`). This file records each dependency and its license so that
license compliance can be audited. No dependency uses a copyleft license that
would encumber this project.

## Runtime dependencies

| Package     | Version  | License      |
| ----------- | -------- | ------------ |
| fastapi     | 0.115.6  | MIT          |
| pydantic    | 2.10.4   | MIT          |
| uvicorn     | 0.34.0   | BSD-3-Clause |
| asyncua     | 1.1.6    | LGPL-3.0-only (dynamic use only; read-only OPC UA client) |
| pymodbus    | 3.7.4    | BSD-3-Clause (read function codes only) |
| defusedxml  | 0.7.1    | PSF-2.0 (used by services/watertwin-ingest to detect/reject XML XXE attacks in uploads) |
| python-multipart | 0.0.20 | Apache-2.0 (multipart form parsing for file uploads in services/watertwin-ingest) |
| httpx       | 0.28.1   | BSD-3-Clause (runtime HTTP client for the watertwin-ingest reconciler; also a dev dep elsewhere) |
| python-multipart | 0.0.20 | Apache-2.0 (streamed uploads; watertwin-ingest only) |
| openpyxl    | 3.1.5    | MIT (watertwin-ingest; read_only + data_only, never executes macros) |
| charset-normalizer | 3.4.7 | MIT (watertwin-ingest; CSV encoding detection) |

### Transitive runtime dependencies

| Package          | Version  | License      |
| ---------------- | -------- | ------------ |
| starlette        | 0.41.3   | BSD-3-Clause |
| pydantic-core    | 2.27.2   | MIT          |
| annotated-types  | 0.7.0    | MIT          |
| anyio            | 4.14.2   | MIT          |
| sniffio          | 1.3.x    | MIT/Apache-2.0 |
| idna             | 3.18     | BSD-3-Clause |
| click            | 8.4.2    | BSD-3-Clause |
| h11              | 0.16.0   | MIT          |
| typing-extensions| 4.x      | PSF          |
| et-xmlfile       | 2.0.0    | MIT (openpyxl dependency) |

## watertwin-ingest service dependencies

Additional runtime dependencies of the `services/watertwin-ingest` bulk
file-import service (pinned in `services/watertwin-ingest/requirements.txt`).
None is copyleft.

| Package    | Version  | License      |
| ---------- | -------- | ------------ |
| pyarrow    | 25.0.0   | Apache-2.0 (streamed Parquet reading) |
| pyshp      | 3.1.4    | MIT (pure-Python shapefile reader) |
| pyproj     | 3.7.2    | MIT (bundles PROJ, MIT/ISC; CRS reprojection) |
| defusedxml | 0.7.1    | PSF-2.0 (hardened XML parsing) |

## Development-only dependencies

| Package  | Version  | License      |
| -------- | -------- | ------------ |
| httpx    | 0.28.1   | BSD-3-Clause |
| pytest   | 8.3.4    | MIT          |
| ruff     | 0.8.4    | MIT          |

> Development dependencies are used for testing and linting only and are not
> shipped as part of the deployable service.
