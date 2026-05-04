#!/bin/sh
set -e

# Select nginx config template based on whether a secret path is configured.
# Strategy A (or A+B): PROXY_SECRET_PATH is set — use the path-gated template.
# Strategy B only:     PROXY_SECRET_PATH is empty — use the open proxy template.
if [ -n "${PROXY_SECRET_PATH:-}" ]; then
    envsubst '${SNOWFLAKE_HOST} ${SNOWFLAKE_PORT} ${PROXY_SECRET_PATH}' \
        < /etc/nginx/nginx.conf.template \
        > /etc/nginx/nginx.conf
else
    envsubst '${SNOWFLAKE_HOST} ${SNOWFLAKE_PORT}' \
        < /etc/nginx/nginx.conf.open.template \
        > /etc/nginx/nginx.conf
fi

nginx -t
exec nginx -g 'daemon off;'
