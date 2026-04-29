#!/bin/sh
set -e

# Substitute only these variables so envsubst does not touch any other
# $ references that nginx itself uses internally.
envsubst '${SNOWFLAKE_HOST} ${SNOWFLAKE_PORT} ${PROXY_SECRET_PATH}' \
    < /etc/nginx/nginx.conf.template \
    > /etc/nginx/nginx.conf

nginx -t
exec nginx -g 'daemon off;'
