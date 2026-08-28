#!/bin/sh
set -eu

cp /etc/ssl/certs/java/cacerts /tmp/cacerts
keytool -importcert -noprompt -alias m15-local-ca -file /ca/ca.crt \
  -keystore /tmp/cacerts -storepass changeit >/dev/null
export JAVA_TOOL_OPTIONS="-Djavax.net.ssl.trustStore=/tmp/cacerts -Djavax.net.ssl.trustStorePassword=changeit"

exec python3 /zap/zap-baseline.py \
  -t https://host.docker.internal \
  -m 1 \
  -J zap-report.json \
  -r zap-report.html \
  -z "-config replacer.full_list(0).description=local-host -config replacer.full_list(0).enabled=true -config replacer.full_list(0).matchtype=REQ_HEADER -config replacer.full_list(0).matchstr=Host -config replacer.full_list(0).replacement=localhost"
