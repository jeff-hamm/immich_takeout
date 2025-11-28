FROM python:3.12-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir flask

COPY app.py /app/
COPY templates /app/templates/

EXPOSE 5000

CMD ["python", "app.py"]
