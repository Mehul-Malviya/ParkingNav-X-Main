FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure experiments directory exists
RUN mkdir -p experiments/results experiments/runs experiments/models

EXPOSE 8000

CMD ["uvicorn", "digital_twin.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
