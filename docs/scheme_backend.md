## Informe técnico: Backend Robonet (video por chunks + SyncMeta)

Este documento describe cómo el backend FastAPI coordina:
- **Chunks de video** (multipart) desde la app móvil hasta **Cloudflare R2**
- **Metadatos de sincronización** (`syncmeta`) por chunk de video (para alinear ventanas temporales con IMU)
- Chunks de **IMU** (NDJSON) con el mismo patrón **presign/PUT/confirm**: la app móvil sube IMU del **teléfono** por cada `partNumber` junto al video; el kit/headset puede aportar otro origen en el futuro mezclando líneas en el mismo formato

> Punto clave del diseño: **los binarios (chunks) nunca pasan por el backend**. El backend solo:
> - autentica y valida permisos/estado
> - genera **presigned URLs** para subir partes a R2
> - persiste metadata en **Firestore**
> - completa/aborta multipart uploads en R2 cuando corresponde

---

## Arquitectura general

```mermaid
graph TB
  subgraph Mobile["📱 App móvil"]
    M1["Timer de chunks + cámara"]
    M2["POST syncmeta por chunk"]
    M3["POST chunks/presign (video + imu)"]
    M4["PUT directo a R2 (mp4 + ndjson)"]
    M5["POST chunks/confirm (video + imu, ETag)"]
  end

  subgraph Backend["⚙️ Backend FastAPI"]
    B1["get_current_user() valida JWT Firebase"]
    B2["/sessions crea sesión + multipart uploads"]
    B3["/chunks/presign genera URL de upload_part (R2)"]
    B4["/chunks/confirm persiste receipts en Firestore"]
    B5["/sessions/{id}/complete ensambla final.mp4 + final.ndjson"]
    B6["/syncmeta guarda metadatos por parte"]
  end

  subgraph Firebase["🔥 Firebase"]
    F1["Auth (verify_id_token)"]
    F2["Firestore: users / sessions / chunks / syncMeta / processingQueue"]
  end

  subgraph R2["☁️ Cloudflare R2 (S3 compatible)"]
    R1["multipart final.mp4 y final.ndjson"]
  end

  M1 --> B2
  M2 --> B6 --> F2
  M3 --> B3 --> R2
  M4 --> R1
  M5 --> B4 --> F2
  B5 --> R1
  B1 --> F1
```

---

## Start del backend (`app/main.py`)

- Inicializa logging con `setup_logging()` y logger de la app.
- En el `lifespan` (startup):
  - llama `init_firebase()` una sola vez
- Registra routers:
  - `/auth/*` -> `routers/auth.py`
  - `/sessions/*` -> `routers/sessions.py`
  - `/sessions/*` -> `routers/uploads.py` (chunks/presign/confirm/complete/abort)
  - `/sessions/*` -> `routers/sync_signals.py` (syncmeta)
- `CORS` está configurado con `allow_origins=["*"]`
- Endpoint:
  - `GET /health`

---

## Autenticación: Firebase ID Token

El backend usa `HTTPBearer` y `Authorization: Bearer <idToken>`.

Ruta protegida -> `get_current_user()` -> `verify_token()` con `firebase_admin.auth.verify_id_token`.

Si el token es inválido o expiró: responde **401**.

---

## Modelos persistidos en Firestore

### `users/{uid}`
Creado/actualizado desde el móvil en:
- `POST /auth/register-device`

### `sessions/{sessionId}`
Creado en:
- `POST /sessions`

Campos importantes:
- `status`: actualmente `"recording"` (el backend permite presign con `recording` o `uploading`, pero no hay un endpoint que setee `"uploading"` en este código)
- `videoKey`: `sessions/{sessionId}/video/final.mp4`
- `imuKey`: `sessions/{sessionId}/imu/final.ndjson`
- `videoUpload.uploadId`, `imuUpload.uploadId` (IDs de multipart upload en R2)

### `chunks/{chunkId}`
Creado/mergeado en:
- `POST /sessions/{session_id}/chunks/confirm`

`chunkId` = `"{sessionId}_part{partNumber:03d}"`

Contiene receipts con:
- `videoETag` / `videoStartTsUs` / `videoEndTsUs` (si stream=`video`)
- `imuETag` / `imuStartTsUs` / `imuEndTsUs` / `sensorIds` (si stream=`imu`; ver convención `1001` más abajo)
- `status`:
  - `"videoUploaded"` si solo llegó video
  - `"imuUploaded"` si solo llegó imu
  - `"readyForProcess"` cuando existen ambos receipts (video+imu) para ese `partNumber` (POC de cola)

### `syncMeta/{syncId}`
Persistido en:
- `POST /sessions/{session_id}/syncmeta`

`syncId` = `"{sessionId}_part{partNumber:03d}"`

Contiene:
- ventana temporal del video del chunk: `videoStartTsUs`, `videoEndTsUs`
- ventana temporal del stream IMU asociada a ese chunk: `ptsStart`, `ptsEnd`
- `nonce` (opcional, hoy el móvil no lo envía)
- `consumedAt`, `consumedBy` (cuando la Raspberry lo consuma; hoy es POC)

### `processingQueue/{chunkId}` (POC)
Se crea cuando `confirmChunk` detecta que para ese `partNumber` ya existen receipts de:
- `videoETag` y `imuETag`

---

## Endpoints (detalle real del código)

### Docs / base
- Swagger: `/docs`
- ReDoc: `/redoc`
- Salud: `GET /health`

---

## Health

### `GET /health`
Sin auth.

Respuesta:
```json
{ "status": "ok", "env": "development" }
```

---

## Auth

### `POST /auth/register-device`
- Auth: **sí** (Bearer)
- Body: `RegisterDeviceRequest` (con `deviceInfo` opcional)
- Acción:
  - upsert en `users/{uid}` con `merge=True`
- Respuesta: `UserResponse`

### `GET /auth/me`
- Auth: **sí** (Bearer)
- Acción: lee `users/{uid}` y retorna `UserResponse`

---

## Sessions

### `POST /sessions`
- Auth: **sí** (Bearer)
- Body (`CreateSessionRequest`):
```json
{ "deviceInfo": { "...": "..." } }
```
- Acción:
  - genera `sessionId` (UUID)
  - abre **dos** multipart uploads en R2:
    - video (`video/mp4`) para `sessions/{sessionId}/video/final.mp4`
    - imu (`application/x-ndjson`) para `sessions/{sessionId}/imu/final.ndjson`
  - crea `sessions/{sessionId}` con `status="recording"`
- Respuesta: `SessionResponse`

### `GET /sessions`
- Auth: **sí** (Bearer)
- Acción: lista últimas 50 sesiones del usuario (`startedAt DESC`)

### `GET /sessions/{session_id}`
- Auth: **sí** (Bearer)
- Acción:
  - si no existe: **404**
  - si no pertenece al usuario: **403**
  - si pertenece: retorna `SessionResponse`

---

## Chunks (multipart en R2)

Este backend usa multipart upload en R2, pero el backend **no sube los bytes**:
- genera presigned URL para `upload_part`
- el móvil sube bytes con `PUT`
- el móvil manda de vuelta el `ETag` con `chunks/confirm`

### `POST /sessions/{session_id}/chunks/presign`
- Auth: **sí** (Bearer)
- Body (`PresignRequest`):
```json
{ "partNumber": 1, "stream": "video" }
```
- Acción:
  - valida que la sesión exista y sea del usuario
  - verifica estado grabable: `session.status in {"recording","uploading"}`
  - si `stream == "video"` usa:
    - `session["videoKey"]`
    - `session["videoUpload"]["uploadId"]`
  - si `stream == "imu"` usa:
    - `session["imuKey"]`
    - `session["imuUpload"]["uploadId"]`
  - genera presigned URL para `upload_part` con expiración **2 horas** (`ExpiresIn=7200`)
- Respuesta (`PresignResponse`):
```json
{
  "uploadId": "string",
  "partNumber": 1,
  "stream": "video",
  "presignedUrl": "https://..."
}
```

### PUT del móvil a R2
- El móvil hace `PUT` directo a `presignedUrl`.
- Espera `ETag` en la respuesta.
- Para video, el móvil usa `Content-Type: video/mp4`.
- Para IMU, el móvil usa `Content-Type: application/x-ndjson` (cuerpo = un archivo NDJSON por parte).

### `POST /sessions/{session_id}/chunks/confirm`
- Auth: **sí** (Bearer)
- Body (`ConfirmChunkRequest`):
```json
{
  "partNumber": 1,
  "stream": "video",
  "etag": "\"...\"",
  "startTsUs": 1712345678901234,
  "endTsUs": 1712345682901234,
  "sensorIds": null
}
```
- Para `stream: "imu"`, el cuerpo es el mismo esquema; la app móvil envía típicamente `sensorIds: [1001]` para indicar **IMU integrado del teléfono** (convención documentada; otros IDs quedan para sensores del kit).
- Acción:
  - arma `chunkId = {sessionId}_part{partNumber:03d}`
  - persiste/mergea en `chunks/{chunkId}`:
    - si stream=`video`: guarda `videoETag`, `videoStartTsUs`, `videoEndTsUs`, `videoUploadedAt`
    - si stream=`imu`: guarda `imuETag`, `imuStartTsUs`, `imuEndTsUs`, `sensorIds`, `imuUploadedAt`
  - calcula `status`:
    - si tras el merge existen ambos ETags (video+imu) -> `readyForProcess` y crea `processingQueue/{chunkId}` (POC)
    - si solo llegó video -> `videoUploaded`
    - si solo llegó imu -> `imuUploaded`
- Respuesta (`ConfirmChunkResponse`):
```json
{ "chunkId": "session_part001", "status": "videoUploaded|imuUploaded|readyForProcess" }
```

### `GET /sessions/{session_id}/chunks`
- Auth: **sí** (Bearer)
- Acción: devuelve docs `chunks` de la sesión ordenados por `partNumber`

### `POST /sessions/{session_id}/complete`
- Auth: **sí** (Bearer)
- Acción:
  - carga todos los `chunks` confirmados
  - exige que **cada parte** tenga `videoETag` e `imuETag`
  - llama `complete_multipart_upload()` para:
    - `final.mp4` (usando `videoETag`)
    - `final.ndjson` (usando `imuETag`)
  - actualiza `sessions/{sessionId}` a:
    - `status="complete"`
    - `endedAt=now`
    - `totalChunks=#chunks`
- Error:
  - **400** si faltan receipts (común cuando el móvil aún no sube IMU)

### `DELETE /sessions/{session_id}/abort`
- Auth: **sí** (Bearer)
- Acción:
  - aborta ambos multipart uploads (video+imu) en R2
  - actualiza `sessions/{sessionId}` a `status="aborted"`, `endedAt=now`
  - recomendado al cancelar grabación

---

## Formato NDJSON del stream IMU (teléfono y futuros orígenes)

Cada **línea** es un objeto JSON. El worker / Raspberry debe usar el campo `source` para distinguir orígenes.

### Muestras del IMU del teléfono (`source: phone`)

La app emite líneas por evento de sensor (timestamps en microsegundos Unix de recepción en el dispositivo):

**Acelerómetro**
```json
{"tsUs": 1712345678901234, "source": "phone", "sensor": "accelerometer", "x": 0.0, "y": 0.0, "z": 9.8}
```

**Giroscopio**
```json
{"tsUs": 1712345678901235, "source": "phone", "sensor": "gyroscope", "x": 0.0, "y": 0.0, "z": 0.0}
```

**Magnetómetro** (opcional; si el dispositivo no expone el stream, puede no aparecer)

```json
{"tsUs": 1712345678901236, "source": "phone", "sensor": "magnetometer", "x": 0.0, "y": 0.0, "z": 0.0}
```

### Marcadores cuando no hay datos

Si no hubo muestras en la ventana o falló el acceso a sensores, puede aparecer una línea única como:

```json
{"tsUs": 1712345678901234, "source": "phone", "note": "no_samples", "error": "mensaje opcional"}
```

### Convención `sensorIds` en Firestore

- **`1001`**: IMU integrado del smartphone (valor enviado por la app al confirmar el chunk `imu`).

---

## SyncMeta (sincronización de chunk video -> ventana IMU)

### `POST /sessions/{session_id}/syncmeta`
- Auth: **sí** (Bearer)
- Body (`SyncMetaRequest`):
```json
{
  "partNumber": 1,
  "videoStartTsUs": 1712345678901234,
  "videoEndTsUs": 1712345682901234,
  "ptsStart": 0,
  "ptsEnd": 30000,
  "nonce": null
}
```
- Acción:
  - guarda `syncMeta/{syncId}` con `consumedAt=None`
- Respuesta:
```json
{ "syncId": "...", "status": "stored" }
```

### `GET /sessions/{session_id}/syncmeta/pending` (POC)
- Auth: **sí** (Bearer)
- Acción: devuelve hasta 50 `syncMeta` con `consumedAt == None` (polling)

### `POST /sessions/{session_id}/syncmeta/{part_number}/consume` (POC)
- Auth: **sí** (Bearer)
- Acción: marca `syncMeta/{syncId}` como consumido

---

## Flujo completo en el móvil (lo que SÍ hace hoy)

La app móvil:
1. Crea sesión: `POST /sessions`
2. Durante la grabación, captura IMU del teléfono (acelerómetro, giroscopio, magnetómetro si existe) y agrupa líneas NDJSON por chunk.
3. Cada `_chunkDurationSeconds = 30` (y el último cierre):
   - guarda `syncmeta` con ventana del video del chunk
   - pide `chunks/presign` para `stream:"video"` y sube el MP4; confirma video
   - pide `chunks/presign` para `stream:"imu"`, sube el NDJSON del teléfono (`Content-Type: application/x-ndjson`); confirma IMU con `sensorIds: [1001]`
4. Al detener:
   - `POST /sessions/{id}/complete` cuando cada parte tiene `videoETag` e `imuETag`
5. Al cancelar:
   - `DELETE /sessions/{id}/abort`

```mermaid
sequenceDiagram
  participant App as 📱 Mobile
  participant API as Backend
  participant R2 as R2
  participant FS as Firestore

  App->>API: POST /sessions
  API->>FS: sessions/{id} + crear multipart uploads en R2
  API-->>App: sessionId

  loop chunk de video + IMU teléfono (30s)
    App->>API: POST /sessions/{id}/syncmeta
    API->>FS: syncMeta/{id}_partNNN

    App->>API: POST /sessions/{id}/chunks/presign {partNumber, stream:"video"}
    API->>R2: generate_presigned_url(upload_part)
    API-->>App: presignedUrl

    App->>R2: PUT presignedUrl (video/mp4)
    R2-->>App: ETag

    App->>API: POST /sessions/{id}/chunks/confirm {partNumber, stream:"video", etag, ...}
    API->>FS: chunks/{id}_partNNN (videoETag)

    App->>API: POST /sessions/{id}/chunks/presign {partNumber, stream:"imu"}
    API-->>App: presignedUrl (imu)

    App->>R2: PUT presignedUrl (application/x-ndjson)
    R2-->>App: ETag

    App->>API: POST /sessions/{id}/chunks/confirm {partNumber, stream:"imu", etag, sensorIds:[1001]}
    API->>FS: chunks/{id}_partNNN (imuETag)
  end

  App->>API: POST /sessions/{id}/complete
  API->>FS: valida videoETag + imuETag por cada part
  API-->>App: 400 si falta algún receipt

  alt cancelar grabación
    App->>API: DELETE /sessions/{id}/abort
    API->>R2: abort multipart uploads
    API->>FS: sessions.status="aborted"
  end
```

---

## Coordinación con el móvil (`lib/main.dart`, `AppShell`, `SessionScreen`)

### `lib/main.dart`
- Inicializa Firebase y localización.
- Home: `LoginScreen`.

### `LoginScreen` / `AuthService`
- Firma con Google (Firebase).
- Obtiene `idToken`.
- Llama `POST /auth/register-device` para que el backend cree/actualice `users/{uid}`.
- Luego navega a `AppShell`.

### `AppShell`
- Muestra `SessionScreen` en la barra inferior.

### `SessionScreen` / `_RecordingRoute`
- Al presionar iniciar:
  - pide permisos (camera/microphone)
  - inicializa `RecordingService`
  - llama `POST /sessions` y obtiene `sessionId`
  - navega a `_RecordingRoute`
- `_RecordingRoute`:
  - permite las cuatro orientaciones del dispositivo durante la grabación y orienta la vista previa con sensor nativo (`native_device_orientation`)
  - arranca `PhoneImuRecorder` (streams de `sensors_plus`) y la grabación de video
  - cada 30s rota chunks (partNumber empieza en 1)
  - por chunk ejecuta:
    - `POST /syncmeta`
    - `POST /chunks/presign` + `PUT` + `POST /chunks/confirm` para **video** y para **imu** (NDJSON del teléfono)

---

## Qué falta / extensiones

El flujo **video + IMU desde el teléfono** ya permite completar la sesión. Posibles extensiones:
1. **Mezclar** en el mismo NDJSON líneas del kit/headset (`source` distinto de `phone`) manteniendo un solo `partNumber` por ventana, o abrir un segundo stream R2 si se requiere aislar binarios.
2. **Calibración** y fusión de marcas de tiempo entre reloj del teléfono y del kit (hoy `tsUs` es tiempo del dispositivo al recibir el evento).

Cuando existan receipts de video e IMU para cada parte:
- `confirmChunk` marcará `readyForProcess` y creará `processingQueue` (POC)
- `completeSession` podrá ensamblar:
  - `sessions/{id}/video/final.mp4`
  - `sessions/{id}/imu/final.ndjson`

