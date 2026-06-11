# LibreChat compatible code interpreter

A FastAPI-based code interpreter service that provides code execution and file management capabilities. This service is compatible with the LibreChat Code Interpreter API specification.

> [!NOTE]
> This project is mostly a proof of concept and is not intended to be used in production.   
> 
> For production ready solution and to support the amazing work of LibreChat maintainers use the [LibreChat Code Interpreter](https://code.librechat.ai/pricing).

## Features

- Easy deployment with single docker compose file
- Code is executed in a isolated Docker container sandbox, custom images supported
- Supports file upload and download
- Supports concurrent code execution
- Supports Python and R languages (possibility to extend to other languages)
- RESTful API with OpenAPI documentation

https://github.com/user-attachments/assets/ca74549e-0e32-4659-81a8-158ee9132738

## Usage

### Running the project

Run the project with docker compose using `docker compose -f compose.prod.yml up`

It's possible to overwrite the default environment variables defined in [./app/shared/config.py](./app/shared/config.py) by creating a `.env` file in the root directory.
By default the project will create two directories in the root directory: `./config` and `./uploads`.

`config` directory will hold the sqlite database and temp uploaded files.
`uploads` directory will hold the files uploaded by the users. All files uploaded by the users will be, by default, deleted after 24 hours.

### Configuring LibreChat

LibreChat is configured to use the code interpreter API by default.

To configure LibreChat to use the local code interpreter, set the following environment variables in LibreChat:

```ini
LIBRECHAT_CODE_API_KEY=<any-value-here>
LIBRECHAT_CODE_BASEURL=http(s)://host:port/v1/librechat # for local testing use to point to host IP http://host.docker.internal:8000/v1/librechat
```


## Development

### Installation

1. Install dependencies using uv:
```bash
uv sync --all-extras
source .venv/bin/activate
```

## Running the Application

1. Start the development server:
```bash
docker compose up
```

The API will be available at `http://localhost:8000`. The OpenAPI documentation can be accessed at `http://localhost:8000/docs`.


### Running tests

Most tests exercise code execution, which starts **sandbox containers via the host Docker daemon**. That requires:

1. **A reachable Docker socket** — the app talks to Docker on the host, not inside its own filesystem.
2. **Correct `HOST_PATH`** — session files live at `./uploads` inside the app, but sandbox bind mounts must use the **host** path (e.g. `/your/project/uploads/<session_id>`). Compose sets `HOST_PATH=$PWD` for this; running pytest with the wrong value causes `bind source path does not exist` errors.

The simplest way to satisfy both is to run tests in the same environment as the dev server:

```bash
docker compose up -d
docker compose exec code-interpreter uv run pytest tests -v
```

Test logs are written to `logs/test.log`.

**Alternative — run on the host** (without `docker compose exec`):

```bash
uv sync --all-extras
uv run pytest tests -v
```

The first run may take longer while sandbox images (`jupyter/scipy-notebook`, `jupyter/r-notebook`, `node:24-slim`) are pulled.

