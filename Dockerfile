FROM python:3-slim

COPY requirements.txt ./
COPY poona.py ./

RUN pip3 install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "./poona.py" ]