## Backend Robonet — Video + IMU Streaming

Backend en **Python + FastAPI** que coordina el streaming de video e IMU desde la app móvil hacia **Cloudflare R2** (archivos) y **Firebase Firestore** (metadata y estado de sesiones).

- **Repositorio raíz backend**: `backend/`
- **App principal**: `app/main.py`
- **Gestor de dependencias**: `pyproject.toml` (build con Hatch)

---

## Arquitectura general

- **Cliente móvil**
  - Captura cámara + IMU.
  - Cada ~30 s genera un *chunk* de video `.mp4` y un chunk de IMU en memoria.
  - Llama al backend para:
    - Crear sesión.
    - Pedir presigned URLs para cada chunk.
    - Confirmar ETags de los uploads.
    - Marcar la sesión como completada/abortada.

- **Backend FastAPI (este proyecto)**
  - Verifica tokens de **Firebase Auth** en cada request.
  - Crea y administra sesiones en **Firestore** (`sessions`, `chunks`, `users`).
  - Genera **presigned URLs** S3-compatibles para Cloudflare R2.
  - Orquesta el `CompleteMultipartUpload` de los objetos finales (video e IMU).

- **Servicios externos**
  - **Firebase Auth**: autenticación del usuario (ID Token JWT).
  - **Firestore**: documentos de `users`, `sessions`, `chunks`.
  - **Cloudflare R2**: almacenamiento de video + IMU (multipart uploads).
  - (Opcional) **Railway / Render**: despliegue del contenedor Docker del backend.

---

## Estructura del proyecto

Estructura esperada del backend (simplificada):

- `backend/`
  - `app/`
    - `main.py` → inicializa FastAPI, CORS, routers y Firebase; define entrypoint `start()`.
    - `config.py` → configuración y variables de entorno centralizadas (`Settings`).
    - `dependencies.py` → dependencias comunes (auth middleware `get_current_user`).
    - `routers/`
      - `auth.py` → endpoints de usuario / dispositivo.
      - `sessions.py` → creación y consulta de sesiones.
      - `uploads.py` → presign de chunks, confirmación y completado de sesiones.
    - `services/`
      - `firebase.py` → inicializa Firebase, expone `get_db()` y `verify_token()`.
      - `r2.py` → cliente S3/R2, presigned URLs y operaciones multipart.
      - `sessions.py` → (opcional) lógica de dominio extra de sesiones.
    - `models/`
      - `session.py` → modelos Pydantic para requests/responses de sesiones y chunks.
      - `chunk.py`, `user.py` → otros modelos.
  - `pyproject.toml` → dependencias, scripts (`serve`) y configuración de herramientas.
  - `Dockerfile` → imagen de producción (FastAPI + Uvicorn).
  - `.env` → variables de entorno locales (no se commitea).

---

## Configuración de servicios externos

### 1. Firebase

**Rol en el sistema**

- **Auth**: la app móvil se loguea directo contra Firebase Auth (email/password, Google, etc.) y obtiene un **ID Token**.
- El backend recibe ese token en `Authorization: Bearer <idToken>` y lo valida con `firebase-admin`.
- **Firestore**: persiste:
  - `users/{uid}` → datos de usuario y dispositivo.
  - `sessions/{sessionId}` → estado y metadatos de la sesión.
  - `chunks/{chunkId}` → ETags y orden de chunks.

**Qué tienes que configurar**

1. Crear proyecto en Firebase Console.
2. Habilitar:
   - **Authentication** (al menos Email/Password).
   - **Firestore Database** (modo producción).
3. En `Configuración del proyecto → Cuentas de servicio → Generar nueva clave privada`.
   - Descarga el JSON y guárdalo como `firebase-credentials.json` en la carpeta `backend/`.
   - Añádelo a `.gitignore` (no se sube al repo).
4. Reglas mínimas recomendadas de Firestore (resumen):
   - `users/{userId}`: solo el propio usuario puede leer/escribir.
   - `sessions/{sessionId}`: solo el dueño puede crear/leer/actualizar/eliminar.
   - `chunks/{chunkId}`: escritura permitida para usuarios autenticados (ajusta según tus necesidades).

**Variables relevantes**

- `FIREBASE_CREDENTIALS_PATH` → ruta al JSON de credenciales (ej. `firebase-credentials.json`), usada por `app.config.Settings` y `app.services.firebase`.

---

### 2. Cloudflare R2

**Rol en el sistema**

- Almacenar **video** (`.mp4`) e **IMU** (`.ndjson`) usando **multipart upload** compatible con S3.
- Los clientes **nunca** suben archivos al backend directamente; siempre suben directo a R2 con presigned URLs generadas por el backend.

**Qué tienes que configurar**

1. En el dashboard de Cloudflare → **R2 Object Storage → Create bucket**
   - Nombre recomendado: `sessions-poc` (o similar).
   - Región: WNAM (suele ir bien para LATAM).
2. Configurar **CORS** del bucket (para que el cliente pueda hacer `PUT` y leer `ETag`):

   ```json
   [
     {
       "AllowedOrigins": ["*"],
       "AllowedMethods": ["GET", "PUT", "HEAD"],
       "AllowedHeaders": ["*"],
       "ExposeHeaders": ["ETag"],
       "MaxAgeSeconds": 7200
     }
   ]
   ```

3. Crear **API Token**:
   - Permisos: `Object Read & Write`.
   - Scope: solo el bucket de este proyecto.
   - Guarda:
     - `Account ID`
     - `Access Key ID`
     - `Secret Access Key`

**Layout de objetos recomendado (por chunk)**

- `sessions/{userId}/{sessionId}/video/partNNN.mp4` → cada chunk de video (30s).
- `sessions/{userId}/{sessionId}/imu/partNNN.ndjson` → cada chunk IMU (30s).

R2 es object storage: los “directorios” son prefijos del key. En la UI se ven como carpetas cuando se navega por prefijo.

**Variables relevantes**

- `R2_ACCOUNT_ID` → ID de cuenta de Cloudflare.
- `R2_ACCESS_KEY_ID` → access key del token.
- `R2_SECRET_ACCESS_KEY` → secret key del token.
- `R2_BUCKET_NAME` → nombre del bucket (por defecto `sessions-poc`).

El endpoint completo de R2 se construye automáticamente en `app.config.Settings` a partir de `R2_ACCOUNT_ID`.

---

### 3. Plataforma de despliegue (Railway / Render)

**Rol en el sistema**

- Ejecutar el contenedor Docker con el backend FastAPI, exponiendo el puerto 8000 al exterior.
- Proveer un panel para gestionar variables de entorno y despliegues continuos (si se usa con GitHub).

**Qué tienes que configurar (Railway como ejemplo)**

1. Tener la imagen Docker lista (ver sección Docker más abajo).
2. En Railway:
   - Crear un nuevo proyecto.
   - Configurar el servicio como **Docker**.
3. Definir variables de entorno en el panel:

   - `R2_ACCOUNT_ID`
   - `R2_ACCESS_KEY_ID`
   - `R2_SECRET_ACCESS_KEY`
   - `R2_BUCKET_NAME`
   - `FIREBASE_CREDENTIALS_PATH` o, en producción, una variable tipo `FIREBASE_CREDENTIALS_JSON` que contenga el JSON de servicio (entonces el código de `firebase.py` debe decodificarla).
   - `APP_ENV=production`
   - `CHUNK_DURATION_SECONDS` (si quieres sobreescribir el default).

4. Conectar con GitHub opcionalmente para despliegue automático en cada push.

---

## Variables de entorno (.env)

Ejemplo de `.env` local en el directorio `backend/`:

```env
# Cloudflare R2
R2_ACCOUNT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
R2_ACCESS_KEY_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
R2_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
R2_BUCKET_NAME=sessions-poc

# Firebase
FIREBASE_CREDENTIALS_PATH=firebase-credentials.json

# App
APP_ENV=development
CHUNK_DURATION_SECONDS=30
```

Archivos que **no** se deben commitear:

- `.env`
- `firebase-credentials.json`
- `venv/`
- `__pycache__/`, `*.pyc`

---

## Entrypoints principales y su rol

### 1. Entrypoint Python (script `serve` y ejecución directa)

- En `pyproject.toml`:

  - `[project.scripts].serve = "app.main:start"`

- En `app/main.py`:
  - Función `start()`:
    - Es el **entrypoint** para levantar el servidor Uvicorn desde CLI:
      - `python -m app.main` (vía `if __name__ == "__main__": start()`).
      - `hatch run serve` (usa el script configurado).
    - Lanza `uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=...)`.
    - El flag `reload` depende de `APP_ENV` (se activa en `development`).

**Uso típico en local**:

- Con entorno virtual activo y dependencias instaladas:
  - `hatch run serve`
  - o `uvicorn app.main:app --reload --port 8000`

### 2. Entrypoint FastAPI (`app/main.py`)

- `FastAPI(...)` crea la aplicación con:
  - Título: `Robonet Sensor Backend`.
  - Descripción: streaming de video e IMU a R2.
  - Rutas de documentación:
    - Swagger UI: `/docs`
    - ReDoc: `/redoc`
- Middleware:
  - `CORSMiddleware` con `allow_origins=["*"]` (ajustar en producción).
- Eventos:
  - `@app.on_event("startup")`: llama a `init_firebase()` para inicializar Firebase/Firestore al arrancar.
- Routers:
  - `app.include_router(auth.router, prefix="/auth", tags=["auth"])`
  - `app.include_router(sessions.router, prefix="/sessions", tags=["sessions"])`
  - `app.include_router(uploads.router, prefix="/sessions", tags=["uploads"])`
- Endpoint de salud:
  - `GET /health` → `{ "status": "ok", "env": settings.app_env }`
  - Útil para health checks en Railway/Render y monitorización.

### 3. Entrypoint Docker (`Dockerfile`)

- Imagen base: `python:3.12-slim`.
- Copia `requirements.txt` / dependencias (o `pyproject.toml` según configuración final).
- Copia el código de `app/`.
- Expone puerto `8000`.
- Comando por defecto:
  - `uvicorn app.main:app --host 0.0.0.0 --port 8000`

Este es el entrypoint que usarán Railway, Render o cualquier orquestador que lance el contenedor.

---

## Routers y endpoints principales

### 1. Router `auth` (`/auth`)

- **`POST /auth/register-device`**
  - **Rol**: registrar/actualizar la información del dispositivo del usuario en Firestore (`users/{uid}`).
  - **Auth**: requiere `Authorization: Bearer <Firebase ID Token>`.
  - **Body**: `device_info: dict` (modelo a tu gusto).

- **`GET /auth/me`**
  - **Rol**: devolver perfil básico del usuario (mezcla de datos de Firebase + Firestore).
  - **Auth**: mismo esquema de bearer token.

### 2. Router `sessions` (`/sessions`)

- **`POST /sessions`**
  - **Rol**: crear una nueva sesión de grabación para el usuario.
  - Crea documento en `sessions/{sessionId}` con:
    - `status="recording"`, `startedAt`, `videoKey`, `imuKey`, `videoUpload`, `imuUpload`, etc.
    - También crea los **multipart uploads** iniciales en R2 (uno para video y otro para IMU).
  - **Respuesta**: `SessionResponse` con `sessionId`, `userId`, `status`, `startedAt`, `videoKey`, `imuKey`.

- **`GET /sessions`**
  - **Rol**: listar las últimas sesiones del usuario autenticado.
  - Queréa Firestore filtrando por `userId` y ordenando por `startedAt` descendente.

- **`GET /sessions/{session_id}`**
  - **Rol**: obtener detalles de una sesión concreta (status, claves, timestamps, etc.).
  - Verifica que la sesión pertenezca al usuario (`userId` == `uid`).

### 3. Router `uploads` (`/sessions/...`) 

- **`POST /sessions/{session_id}/chunks/presign`**
  - **Body**: `{ "partNumber": N }`.
  - **Rol**:
    - Verifica que la sesión exista y sea del usuario.
    - Genera dos presigned URLs de tipo `upload_part`:
      - Una para el chunk de video.
      - Otra para el chunk de IMU.
    - Devuelve `uploadId` (de video) + URLs + `partNumber`.
  - Este endpoint se llama **antes** de subir cada chunk.

- **`POST /sessions/{session_id}/chunks/confirm`**
  - **Body**: `{ "partNumber", "videoETag", "imuETag" }`.
  - **Rol**:
    - Persistir en `chunks/{chunkId}` la información de cada parte subida.
    - `chunkId` suele ser algo como `{sessionId}_part{NNN}`.
    - Marca `status="uploaded"` y guarda `uploadedAt`.

- **`POST /sessions/{session_id}/complete`**
  - **Rol**:
    - Lee todos los chunks de Firestore filtrando por `sessionId` y ordenados por `partNumber`.
    - Construye las listas de partes `[{PartNumber, ETag}, ...]`.
    - Llama a `complete_multipart_upload` en `app.services.r2` para:
      - El objeto de video final (`videoKey`).
      - El objeto de IMU final (`imuKey`).
    - Actualiza la sesión a `status="complete"`, setea `endedAt` y `totalChunks`.

- **`DELETE /sessions/{session_id}/abort`**
  - **Rol**:
    - Llamar a `abort_multipart_upload` en R2 para los uploads de video e IMU.
    - Marcar la sesión en Firestore como `status="aborted"` y setear `endedAt`.

---

## Flujo completo de una sesión (vista alta nivel)

1. **Login en móvil**
   - La app móvil se autentica con Firebase Auth y obtiene un **ID Token**.
   - Ese token se envía en cada request al backend (`Authorization: Bearer ...`).

2. **Registrar dispositivo (opcional pero recomendado)**
   - `POST /auth/register-device` con info del dispositivo.

3. **Crear sesión**
   - `POST /sessions` → backend crea:
     - Documento `sessions/{sessionId}`.
     - Multipart upload de video e IMU en R2.

4. **Grabar y subir chunks**
   - Por cada chunk \(N\):
     1. `POST /sessions/{sessionId}/chunks/presign` con `partNumber=N`.
     2. Cliente:
        - Serializa IMU a NDJSON.
        - Hace `PUT` directo a las presigned URLs (video e IMU en paralelo).
        - Lee los `ETag` devueltos por R2.
     3. `POST /sessions/{sessionId}/chunks/confirm` con `partNumber`, `videoETag`, `imuETag`.
     4. (Opcional) Guarda info local para reintentos.

5. **Completar sesión**
   - Cuando no hay más chunks:
     - `POST /sessions/{sessionId}/complete`.
     - El backend arma las partes, llama a `CompleteMultipartUpload` en R2 y marca la sesión como `complete`.

6. **Consultar sesiones**
   - `GET /sessions` y `GET /sessions/{sessionId}` para leer el histórico y detalles.

7. **Abortar sesión (si algo falla antes de completar)**
   - `DELETE /sessions/{sessionId}/abort` para cancelar los multipart uploads en R2 y marcar la sesión como abortada.

---

## Cómo levantar el backend en local

1. **Crear y activar entorno virtual (opcional pero recomendado)**

   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate  # Linux/Mac
   # .venv\Scripts\activate   # Windows
   ```

2. **Instalar dependencias**

   ```bash
   pip install hatch
   hatch env create
   ```

   o bien directamente:

   ```bash
   pip install -e .
   ```

3. **Configurar `.env` y credenciales de Firebase**

   - Crear `.env` como en el ejemplo anterior.
   - Colocar `firebase-credentials.json` en `backend/` (o ajustar `FIREBASE_CREDENTIALS_PATH`).

4. **Arrancar el servidor**

   - Con Hatch:

     ```bash
     hatch run serve
     ```

   - O con Uvicorn directo:

     ```bash
     uvicorn app.main:app --reload --port 8000
     ```

5. **Probar la API**

   - Documentación interactiva:
     - Swagger UI: `http://localhost:8000/docs`
     - ReDoc: `http://localhost:8000/redoc`
   - Health check:
     - `GET http://localhost:8000/health`

---

## Notas de producción

- **CORS**:
  - En `app/main.py` se permite `allow_origins=["*"]` para desarrollo.
  - En producción, restringe a los dominios reales de tu app (ej. `["https://app.robonet.com"]`).

- **Tokens de Firebase**:
  - Asegúrate de que el cliente renueve el ID Token cuando expire (Firebase SDK ya maneja esto).

- **Logs y observabilidad**:
  - Añade logging estructurado a los routers/servicios clave (especialmente en `uploads`).
  - Puedes usar health checks (`/health`) para monitorizar el backend en Railway/Render.

- **Migración futura a otra DB**:
  - Firestore es suficiente para POC y primeras iteraciones.
  - Cuando necesites queries más complejas o analítica pesada, podrías mover la capa de persistencia a PostgreSQL manteniendo intacta la interfaz HTTP (routers FastAPI).

# Robonet Backend — Video + IMU Streaming

Backend en Python/FastAPI para recibir sesiones de grabación de video e IMU desde la app móvil, coordinar uploads directos a Cloudflare R2 y persistir metadata en Firebase Firestore.

## Stack

| Capa | Tecnología |
|------|-----------|
| API | Python 3.12 + FastAPI + Uvicorn |
| Auth | Firebase Auth (tokens JWT) |
| DB | Firestore (metadata y estados) |
| Storage | Cloudflare R2 (video MP4 + IMU NDJSON) |
| SDK R2 | boto3 (S3-compatible) |
| Deploy | Docker en Railway o Render |

## Estructura

```
backend/
├── app/
│   ├── main.py            # FastAPI app init + routers
│   ├── config.py          # Settings centralizadas (pydantic-settings)
│   ├── dependencies.py    # Auth middleware (Firebase token verification)
│   ├── routers/
│   │   ├── auth.py        # POST /auth/register-device, GET /auth/me
│   │   ├── sessions.py    # CRUD de sesiones
│   │   └── uploads.py     # Presign, confirm chunk, complete, abort
│   ├── services/
│   │   ├── firebase.py    # Firebase manager (init, get_db, verify_token)
│   │   └── r2.py          # R2/S3 multipart upload helpers
│   └── models/
│       ├── session.py     # Pydantic models para sesiones y uploads
│       ├── chunk.py       # Pydantic model para chunks
│       └── user.py        # Pydantic models para usuarios
├── tests/
│   ├── conftest.py        # Fixtures con mocks de Firebase y R2
│   ├── test_health.py
│   └── test_sessions.py
├── pyproject.toml
├── Dockerfile
├── .env.example
└── .gitignore
```

## Setup local

### 1. Clonar y crear entorno virtual

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
```

### 2. Instalar dependencias

```bash
pip install -e ".[dev]"
```

### 3. Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env con tus credenciales reales
```

### 4. Credenciales de Firebase

Descargá el service account JSON desde Firebase Console → Configuración → Cuentas de servicio y guardalo como `firebase-credentials.json` en la raíz del proyecto. **Nunca lo commities.**

### 5. Arrancar en desarrollo

```bash
uvicorn app.main:app --reload --port 8000
```

O usando el entrypoint del pyproject:

```bash
pip install -e .
serve
```

Swagger UI disponible en http://localhost:8000/docs

## Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/auth/register-device` | Registrar dispositivo |
| `GET` | `/auth/me` | Perfil del usuario |
| `POST` | `/sessions` | Crear sesión (abre multipart en R2) |
| `GET` | `/sessions` | Listar sesiones del usuario |
| `GET` | `/sessions/{id}` | Detalle de sesión |
| `POST` | `/sessions/{id}/chunks/presign` | Generar presigned URLs para chunk |
| `POST` | `/sessions/{id}/chunks/confirm` | Confirmar chunk subido (guardar ETags) |
| `POST` | `/sessions/{id}/complete` | Completar sesión (ensamblar en R2) |
| `DELETE` | `/sessions/{id}/abort` | Abortar sesión |

## Tests

```bash
pytest -v
```

## Deploy

### Railway (recomendado para POC)

```bash
npm install -g @railway/cli
railway login && railway init
railway variables set R2_ACCOUNT_ID=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... R2_BUCKET_NAME=sessions-poc
# Credenciales Firebase en base64:
railway variables set FIREBASE_CREDENTIALS_B64=$(base64 -w 0 firebase-credentials.json)
railway up
```

### Render

1. Subí el código a GitHub
2. New Web Service → Docker runtime → conectar repo
3. Agregar variables de entorno en el dashboard
4. Deploy automático en cada push a `main`

## Variables de entorno

Ver `.env.example` para la lista completa y documentación de cada variable.
