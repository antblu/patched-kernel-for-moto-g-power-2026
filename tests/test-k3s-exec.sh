#!/usr/bin/env bash
# Verify the container root and non-root UID before running other streaming tests.
set -euo pipefail
if [[ $# != 4 ]]; then
    echo "Usage: $0 KUBECONFIG CONTEXT PHONE_NODE ARM64_BUSYBOX_IMAGE_DIGEST" >&2
    exit 2
fi
kube=(kubectl)
if [[ -n ${K3S_BINARY:-} ]]; then kube=("$K3S_BINARY" kubectl); fi
kube+=(--kubeconfig="$1" --context="$2" --request-timeout=90s)
node=$3
image=$4
if [[ ! $node =~ ^[a-z0-9][a-z0-9.-]*$ || ! $image =~ ^[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}$ ]]; then
    echo "Expected a node name and a digest-pinned BusyBox image" >&2
    exit 2
fi
"${kube[@]}" wait --for=condition=Ready "node/$node" --timeout=30s
namespace=$("${kube[@]}" create -f - -o jsonpath='{.metadata.name}' <<'EOF'
apiVersion: v1
kind: Namespace
metadata:
  generateName: k3s-exec-probe-
EOF
)
trap '"${kube[@]}" delete namespace "$namespace" --wait=false >/dev/null' EXIT
marker=$namespace
"${kube[@]}" -n "$namespace" create -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: exec-probe
spec:
  nodeName: $node
  activeDeadlineSeconds: 120
  restartPolicy: Never
  automountServiceAccountToken: false
  containers:
    - name: probe
      image: $image
      securityContext:
        runAsUser: 65534
        runAsNonRoot: true
        allowPrivilegeEscalation: false
      command:
        - /bin/busybox
        - sh
        - -ec
        - |
          printf '%s\n' '$marker' >/tmp/k3s-exec-root
          exec /bin/busybox sleep 100
      readinessProbe:
        exec:
          command: ["/bin/busybox", "test", "-f", "/tmp/k3s-exec-root"]
      resources:
        requests:
          cpu: 10m
          memory: 8Mi
        limits:
          cpu: 100m
          memory: 32Mi
EOF
"${kube[@]}" -n "$namespace" wait --for=condition=Ready pod/exec-probe --timeout=90s
result=$("${kube[@]}" -n "$namespace" exec exec-probe -- /bin/busybox sh -ec '
    test "$(/bin/busybox id -u)" = 65534
    /bin/busybox cat /tmp/k3s-exec-root
')
[[ $result == "$marker" ]]
echo K3S_EXEC_ISOLATION_PASS
