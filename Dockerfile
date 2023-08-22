FROM python:3.8-slim
MAINTAINER YUNXIU
# VOLUME /templates ./
LABEL org.opencontainers.image.title="iact3-action"
LABEL version="1.0"
COPY "entrypoint.sh" "/entrypoint.sh"
COPY "requirements.txt" "/requirements.txt"
COPY "bin/iact3" "/iact3.py"
COPY "./iact3" "/iact3"
RUN chmod +x /entrypoint.sh
RUN apt-get update && apt-get install -y gcc && apt-get install -y jq
RUN pip install -r /requirements.txt
ENTRYPOINT ["/entrypoint.sh"]