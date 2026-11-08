# Shared production Dockerfile for every Friday Python/FastAPI app --
# one Dockerfile, parameterized by which app and port, rather than
# eight near-identical copies (infra/docker-compose.yml's dev stack
# runs these straight off a bind-mounted source tree instead, which
# isn't right for a server that needs to keep running unattended).
#
# Build from the repo root (requirements.txt's `-e packages/py-common`
# is a relative path from here, same reason the dev compose file
# mounts the whole repo rather than just one app's directory):
#   docker build -f infra/python-app.Dockerfile \
#     --build-arg APP_NAME=crm --build-arg APP_PORT=8001 \
#     -t friday-crm .

FROM python:3.12-slim
ARG APP_NAME
ARG APP_PORT
ENV APP_NAME=${APP_NAME}
ENV APP_PORT=${APP_PORT}
WORKDIR /src
COPY packages ./packages
COPY apps/${APP_NAME} ./apps/${APP_NAME}
RUN pip install --no-cache-dir -r apps/${APP_NAME}/requirements.txt
EXPOSE ${APP_PORT}
CMD ["sh", "-c", "python -m friday_common.migrate apps/$APP_NAME $APP_NAME && uvicorn app.main:app --host 0.0.0.0 --port $APP_PORT --app-dir apps/$APP_NAME"]
