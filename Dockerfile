FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data

ENV APP_HOST=0.0.0.0
ENV PORT=8000
ENV QUESTION_SOURCE=auto
ENV DATABASE_URL=sqlite:///./data/app.db

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
