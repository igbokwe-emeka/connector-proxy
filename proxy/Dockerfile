FROM nginx:alpine

# ca-certificates — trusted CA bundle for verifying Snowflake's TLS cert
# gettext     — provides envsubst for config template substitution at startup
RUN apk add --no-cache ca-certificates gettext

COPY nginx.conf.template /etc/nginx/nginx.conf.template
COPY entrypoint.sh       /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
