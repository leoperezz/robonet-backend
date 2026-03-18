FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias del sistema mínimas
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar solo lo necesario para el layer de dependencias (cache-friendly)
COPY pyproject.toml .

# Instalar dependencias de producción
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[standard]" 2>/dev/null || \
    pip install --no-cache-dir \
        fastapi==0.115.0 \
        "uvicorn[standard]==0.30.0" \
        pydantic==2.7.0 \
        pydantic-settings==2.3.0 \
        rich==13.7.1 \
        firebase-admin==6.5.0 \
        boto3==1.35.0 \
        python-dotenv==1.0.1 \
        "python-jose[cryptography]==3.3.0" \
        httpx==0.27.0

# Copiar el código fuente
COPY app/ app/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
