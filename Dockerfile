# Used only for the Day 7 Railway/Docker deploy path — local dev runs the
# app directly with uvicorn (see README), no image build required.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
