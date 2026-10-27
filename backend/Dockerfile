FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/*.py ./
COPY frontend/ ./frontend/
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
