FROM golang:alpine AS builder
WORKDIR /src
RUN apk add --no-cache git
RUN git clone https://github.com/stgnet/bserver.git .
RUN go build -o bserver .

FROM alpine:latest
WORKDIR /app
COPY --from=builder /src/bserver /app/bserver
COPY --from=builder /src/www /srv/www
EXPOSE 8092 8443
CMD ["./bserver", "-base", "/srv/www"]
