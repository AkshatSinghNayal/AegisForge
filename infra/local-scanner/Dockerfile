FROM python:3.12.14-slim
COPY server.py /server.py
COPY site /site
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "/server.py"]
