#!/usr/bin/env bash
# Run from the control plane against a disposable test cluster.
set -euo pipefail

if [[ $# != 4 ]]; then
    echo "Usage: $0 KUBECONFIG CONTEXT PHONE_NODE ARM64_BUSYBOX_IMAGE_DIGEST" >&2
    exit 2
fi

kube=(kubectl)
if [[ -n ${K3S_BINARY:-} ]]; then kube=("$K3S_BINARY" kubectl); fi
kube+=(--kubeconfig="$1" --context="$2" --request-timeout=130s)
node=$3
image=$4
if [[ ! $node =~ ^[a-z0-9][a-z0-9.-]*$ || ! $image =~ ^[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}$ ]]; then
    echo "Expected a node name and a digest-pinned BusyBox image" >&2
    exit 2
fi

"${kube[@]}" wait --for=condition=Ready "node/$node" --timeout=120s
namespace=$("${kube[@]}" create -f - -o jsonpath='{.metadata.name}' <<'EOF'
apiVersion: v1
kind: Namespace
metadata:
  generateName: k3s-phone-probe-
EOF
)
cleanup() {
    "${kube[@]}" delete namespace "$namespace" --wait=false >/dev/null
}
trap cleanup EXIT
"${kube[@]}" -n "$namespace" create -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: phone-probe
spec:
  activeDeadlineSeconds: 120
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
          - matchFields:
              - key: metadata.name
                operator: In
                values: ["$node"]
  restartPolicy: Never
  containers:
    - name: probe
      image: $image
      imagePullPolicy: Always
      securityContext:
        runAsNonRoot: true
        runAsUser: 65534
        runAsGroup: 65534
      command:
        - sh
        - -ec
        - |
          test "\$(uname -m)" = aarch64
          test -r /var/run/secrets/kubernetes.io/serviceaccount/token
          path=\$(awk -F: '\$1 == 0 && \$2 == "" { print \$3 }' /proc/self/cgroup)
          test -n "\$path"
          test "\$(wc -l < /proc/self/cgroup)" -eq 1
          group="/sys/fs/cgroup\${path%/}"
          test "\$(cat "\$group/memory.max")" -eq 33554432
          read -r quota period < "\$group/cpu.max"
          test "\$quota" -gt 0
          test "\$((quota * 10))" -eq "\$period"
          before=\$(awk '\$1 == "nr_throttled" { print \$2 }' "\$group/cpu.stat")
          yes >/dev/null &
          worker=\$!
          trap 'kill "\$worker" 2>/dev/null || true' EXIT
          sleep 2
          kill "\$worker"
          wait "\$worker" || true
          trap - EXIT
          after=\$(awk '\$1 == "nr_throttled" { print \$2 }' "\$group/cpu.stat")
          test "\$after" -gt "\$before"
          echo K3S_ARM64_WORKLOAD_OK
      resources:
        requests:
          cpu: 25m
          memory: 16Mi
        limits:
          cpu: 100m
          memory: 32Mi
EOF
"${kube[@]}" -n "$namespace" wait --for=jsonpath='{.status.phase}'=Succeeded pod/phone-probe --timeout=120s
[[ $("${kube[@]}" -n "$namespace" get pod/phone-probe -o jsonpath='{.spec.nodeName}') == "$node" ]]
"${kube[@]}" -n "$namespace" logs pod/phone-probe | grep -Fx K3S_ARM64_WORKLOAD_OK
echo K3S_AGENT_READY_PASS
