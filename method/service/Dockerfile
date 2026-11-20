FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY method/service/requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt
COPY method /app/method
COPY evidence_install.py /app/evidence_install.py
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "method.service.remote_mcp_server"]
