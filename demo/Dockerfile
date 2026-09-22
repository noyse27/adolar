# Tiny one-shot image used only by docker-compose.demo.yml's "demo-library"
# service: renders the synthetic placeholder music library (see
# generate-library.sh's own header comment for why they're generated here
# instead of shipped as files) and exits. Never part of the normal
# (non-demo) deployment.
FROM alpine:3.20
RUN apk add --no-cache ffmpeg
COPY generate-library.sh /generate-library.sh
RUN chmod +x /generate-library.sh
ENTRYPOINT ["/generate-library.sh"]
