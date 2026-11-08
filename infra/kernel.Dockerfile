# Multi-stage static build -- same pattern as Friday Host's own
# api/Dockerfile. infra/docker-compose.yml's dev stack runs `go run`
# off a bind-mounted source tree for convenience; this is a real
# binary for a server meant to run unattended in production.

FROM golang:1.27-alpine AS build
WORKDIR /src
COPY kernel/go.mod kernel/go.sum* ./
RUN go mod download
COPY kernel/ .
RUN CGO_ENABLED=0 go build -o /out/kernel ./cmd/kernel

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
WORKDIR /app
COPY --from=build /out/kernel ./kernel
COPY kernel/migrations ./migrations
EXPOSE 8080
ENTRYPOINT ["./kernel"]
