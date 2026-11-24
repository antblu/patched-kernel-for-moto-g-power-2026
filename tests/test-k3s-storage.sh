#!/usr/bin/env bash
# Verify a local-path PVC survives replacement of its pod on the phone.
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
"${kube[@]}" wait --for=condition=Ready "node/$node" --timeout=30s
namespace=$("${kube[@]}" create -f - -o jsonpath='{.metadata.name}' <<'EOF'
apiVersion: v1
kind: Namespace
metadata:
  generateName: k3s-storage-probe-
EOF
)
trap '"${kube[@]}" delete namespace "$namespace" --wait=false >/dev/null' EXIT
kube+=(-n "$namespace")
"${kube[@]}" create -f - <<'EOF'
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data
spec:
  storageClassName: local-path
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 16Mi
EOF

for name in writer reader; do
    "${kube[@]}" create -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: $name
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
          - matchFields:
              - key: metadata.name
                operator: In
                values: ["$node"]
  tolerations:
    - key: node.kubernetes.io/unschedulable
      effect: NoSchedule
      operator: Exists
  activeDeadlineSeconds: 120
  restartPolicy: Never
  automountServiceAccountToken: false
  containers:
    - name: probe
      image: $image
      command:
        - /bin/busybox
        - sh
        - -ec
        - |
          printf '%s\n' '$namespace' > /scratch/marker
          test "\$(cat /scratch/marker)" = '$namespace'
          if [ '$name' = writer ]; then
              printf '%s\n' '$namespace' > /persist/marker
              sync
          fi
          test "\$(cat /persist/marker)" = '$namespace'
      resources:
        requests:
          cpu: 10m
          memory: 8Mi
        limits:
          cpu: 100m
          memory: 32Mi
      volumeMounts:
        - {name: data, mountPath: /persist}
        - {name: scratch, mountPath: /scratch}
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: data
    - name: scratch
      emptyDir: {}
EOF
    "${kube[@]}" wait --for=jsonpath='{.status.phase}'=Succeeded "pod/$name" --timeout=120s
    "${kube[@]}" delete pod "$name" --timeout=60s
done
echo K3S_STORAGE_PERSISTENCE_PASS
