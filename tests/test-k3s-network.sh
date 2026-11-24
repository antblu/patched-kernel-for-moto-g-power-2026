#!/usr/bin/env bash
# Run against a disposable cluster. Pass the phone twice to test single-node traffic.
set -euo pipefail

if [[ $# != 5 ]]; then
    echo "Usage: $0 KUBECONFIG CONTEXT PHONE_NODE PEER_NODE BUSYBOX_MULTIARCH_DIGEST" >&2
    exit 2
fi
kube=(kubectl)
if [[ -n ${K3S_BINARY:-} ]]; then kube=("$K3S_BINARY" kubectl); fi
kube+=(--kubeconfig="$1" --context="$2" --request-timeout=130s)
phone=$3
peer=$4
image=$5
uid=${PROBE_UID:-0}
if [[ ! $phone =~ ^[a-z0-9][a-z0-9.-]*$ || ! $peer =~ ^[a-z0-9][a-z0-9.-]*$ ||
      ! $image =~ ^[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}$ || ! $uid =~ ^[0-9]{1,9}$ ]]; then
    echo "Expected two node names, a digest-pinned BusyBox image and a numeric UID" >&2
    exit 2
fi
"${kube[@]}" wait --for=condition=Ready "node/$phone" "node/$peer" --timeout=30s
namespace=$("${kube[@]}" create -f - -o jsonpath='{.metadata.name}' <<'EOF'
apiVersion: v1
kind: Namespace
metadata:
  generateName: k3s-network-probe-
EOF
)
trap '"${kube[@]}" delete namespace "$namespace" --wait=false >/dev/null' EXIT
kube+=(-n "$namespace")
for name in phone peer; do
    node=$phone
    if [[ $name == peer ]]; then node=$peer; fi
    "${kube[@]}" create -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: $name
  labels:
    probe: $name
spec:
  nodeName: $node
  automountServiceAccountToken: false
  activeDeadlineSeconds: 240
  containers:
    - name: http
      image: $image
      securityContext:
        runAsUser: $uid
      command:
        - sh
        - -ec
        - |
          mkdir /tmp/www
          dd if=/dev/zero of=/tmp/www/payload bs=1024 count=256
          exec /bin/busybox httpd -f -p 8080 -h /tmp/www
      readinessProbe:
        tcpSocket:
          port: 8080
      resources:
        requests:
          cpu: 10m
          memory: 8Mi
        limits:
          cpu: 100m
          memory: 32Mi
EOF
done
"${kube[@]}" wait --for=condition=Ready pod/phone pod/peer --timeout=120s
for name in phone peer; do
    "${kube[@]}" expose pod "$name" --port=8080
done
phone_ip=$("${kube[@]}" get pod phone -o jsonpath='{.status.podIP}')
peer_ip=$("${kube[@]}" get pod peer -o jsonpath='{.status.podIP}')
phone_service=$("${kube[@]}" get service phone -o jsonpath='{.spec.clusterIP}')
peer_service=$("${kube[@]}" get service peer -o jsonpath='{.spec.clusterIP}')

fetch() {
    "${kube[@]}" exec "$1" -- /bin/busybox sh -ec '
        /bin/busybox timeout 12 /bin/busybox wget -T 8 -O /tmp/payload "http://$1:8080/payload"
        test "$(wc -c </tmp/payload)" -eq 262144
    ' sh "$2"
}
until_fetch() {
    for attempt in {1..10}; do
        if fetch "$@"; then return 0; fi
        sleep 1
    done
    return 1
}
until_fetch phone "$peer_ip"
until_fetch peer "$phone_ip"
echo 'PASS bidirectional pod IP HTTP (256 KiB payloads)'
until_fetch phone "$peer_service"
until_fetch peer "$phone_service"
echo 'PASS bidirectional ClusterIP HTTP (256 KiB payloads)'
until_fetch phone peer
until_fetch peer phone
echo 'PASS service DNS from both pods'

"${kube[@]}" create -f - <<'EOF'
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-phone-ingress
spec:
  podSelector:
    matchLabels:
      probe: phone
  policyTypes: [Ingress]
EOF
denied=0
for attempt in {1..10}; do
    # Treat only wget's exit status inside a successful exec as a blocked request.
    if [[ $("${kube[@]}" exec peer -- /bin/busybox sh -c '
        if /bin/busybox timeout 8 /bin/busybox wget -q -T 5 -O /dev/null "http://$1:8080/payload"; then
            echo reached
        else
            echo blocked
        fi
    ' sh "$phone_ip") == blocked ]]; then
        fetch phone "$peer_ip"
        denied=1
        break
    fi
    sleep 1
done
[[ $denied == 1 ]]
"${kube[@]}" delete networkpolicy deny-phone-ingress
until_fetch peer "$phone_ip"
echo 'PASS NetworkPolicy denial and recovery'
if [[ $phone == "$peer" ]]; then
    echo 'K3S_SINGLE_NODE_NETWORK_PASS'
else
    echo 'K3S_CROSS_NODE_NETWORK_PASS'
fi
