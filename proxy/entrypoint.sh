#!/bin/sh
set -e

envsubst '${SNOWFLAKE_HOST} ${SNOWFLAKE_PORT}' \
    < /etc/nginx/nginx.conf.template \
    > /etc/nginx/nginx.conf

nginx -t
exec nginx -g 'daemon off;'
