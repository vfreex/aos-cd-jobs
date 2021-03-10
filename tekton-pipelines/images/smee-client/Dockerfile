FROM registry.access.redhat.com/ubi8/ubi:latest
LABEL name="openshift-art/smee-client" \
  maintainer="OpenShift Team Automated Release Tooling <aos-team-art@redhat.com>"

# install smee-client
RUN dnf install -y @nodejs:14 \
  && npm install -g smee-client

USER 1000
CMD ["smee"]
