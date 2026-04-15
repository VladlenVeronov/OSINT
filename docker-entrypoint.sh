#!/bin/sh
# Export all runtime environment variables so cron can see them
printenv | grep -v "^no_proxy\|^PATH\|^HOSTNAME\|^HOME\|^TERM\|^SHLVL\|^_=" \
    > /etc/environment

exec cron -f
