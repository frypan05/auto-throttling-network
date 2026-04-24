# Kubernetes Setup Guide — Nginx Load Balancer Demo

This guide explains how to deploy the auto-throttling-network project to Kubernetes using **Kind** (Kubernetes in Docker), and covers the architecture, networking, and operational aspects in detail.

---

## 📋 Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [Kubernetes Concepts Explained](#kubernetes-concepts-explained)
4. [Detailed Component Breakdown](#detailed-component-breakdown)
5. [How Service Discovery Works](#how-service-discovery-works)
6. [Running & Monitoring](#running--monitoring)
7. [Troubleshooting](#troubleshooting)
8. [Cleanup](#cleanup)

---

## 🚀 Quick Start

### Prerequisites

- **Docker** installed and running
- **Kind** installed: `go install sigs.k8s.io/kind@latest`
- **kubectl** installed: `curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"`
- **Docker images pre-built** from your docker-compose setup

### Step 1: Build Docker Images (if not already done)

```bash
cd /path/to/auto-throttling-network
docker compose build
```

This creates:
- `auto-throttling-network-server:latest` (GraphQL servers)
- `auto-throttling-network-client:latest` (Load generator)

### Step 2: Create Kind Cluster

```bash
kind create cluster --config kubernetes/kind-cluster-config.yaml --name graphql-lb
```

This creates a single-node Kubernetes cluster with port mappings so you can access services from localhost.

### Step 3: Load Docker Images into Kind

```bash
# Load the server image
kind load docker-image auto-throttling-network-server:latest --name graphql-lb

# Load the client image
kind load docker-image auto-throttling-network-client:latest --name graphql-lb
```

Kind needs these images available in its internal Docker daemon.

### Step 4: Create Namespace & RBAC

```bash
kubectl apply -f kubernetes/manifests/00-rbac.yaml
kubectl apply -f kubernetes/manifests/01-namespace.yaml
```

### Step 5: Deploy ConfigMaps (Nginx & Prometheus configs)

```bash
kubectl apply -f kubernetes/manifests/02-nginx-configmap.yaml
kubectl apply -f kubernetes/manifests/03-prometheus-configmap.yaml
kubectl apply -f kubernetes/manifests/09-grafana-provisioning.yaml
```

### Step 6: Deploy All Services

```bash
kubectl apply -f kubernetes/manifests/04-graphql-server.yaml
kubectl apply -f kubernetes/manifests/05-nginx.yaml
kubectl apply -f kubernetes/manifests/06-client.yaml
kubectl apply -f kubernetes/manifests/07-prometheus.yaml
kubectl apply -f kubernetes/manifests/08-grafana.yaml
```

Or apply all at once:
```bash
kubectl apply -f kubernetes/manifests/
```

### Step 7: Verify All Pods Are Running

```bash
kubectl get pods -n graphql-lb -w
```

Wait until all pods show `1/1` READY and `Running` status. This may take 30-60 seconds.

### Step 8: Access Services

Once all pods are ready, open in your browser:

| Service    | URL                  | Purpose              |
|------------|----------------------|----------------------|
| GraphQL    | http://localhost:8080/graphql | GraphQL endpoint via Nginx LB |
| Prometheus | http://localhost:9090 | Metrics query interface |
| Grafana    | http://localhost:3000 | Dashboards (admin/admin) |

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Kind Cluster (graphql-lb)                           │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      graphql-lb Namespace                           │    │
│  │                                                                     │    │
│  │  ┌──────────────────┐        ┌────────────────────────────────┐     │    │    
│  │  │  nginx-*         │        │ graphql-server-0..3 Pods       │     │    │
│  │  │  (1 replica)     │───────▶│ (4 replicas)                   │     │    │
│  │  │  Port: 80        │        │ Port: 8000 each                │     │    │
│  │  └──────────────────┘        │ Health: /health endpoint       │     │    │
│  │         ▲                     └────────────────────────────────┘    │    │
│  │         │                              ▲                            │    │
│  │    client→requests                    │ metrics /metrics            │    │
│  │         │                              │                            │    │
│  │         │                              ▼                            │    │
│  │  ┌──────────────────┐        ┌────────────────────────────────┐     │    │
│  │  │ graphql-client-0 │        │ prometheus-0 Pod              │      │    │
│  │  │ (1 replica)      │        │ Port: 9090                    │      │    │
│  │  │ Looping requests │        │ Scrapes pods every 5s         │      │    │
│  │  └──────────────────┘        └────────────────────────────────┘     │    │
│  │                                        ▲                            │    │
│  │                                        │ metrics read               │    │
│  │  ┌──────────────────────────────┐     │                             │    │
│  │  │ grafana-0 Pod                │◀────┘                             │    │
│  │  │ Port: 3000                   │                                   │    │
│  │  │ Admin: admin/admin           │                                   │    │
│  │  └──────────────────────────────┘                                   │    │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │              Kind Node Port Mappings (to localhost)                 │    │
│  │  NodePort 30080 ──→ localhost:8080  (Nginx/GraphQL)                 │    │
│  │  NodePort 30090 ──→ localhost:9090  (Prometheus)                    │    │
│  │  NodePort 30300 ──→ localhost:3000  (Grafana)                       │    │
│  └─────────────────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Differences from Docker Compose

| Aspect | Docker Compose | Kubernetes |
|--------|---|---|
| **Service Discovery** | Service name → Docker DNS | Service name → Kubernetes DNS (*.svc.cluster.local) |
| **Networking** | All containers on same bridge network | Pod-to-pod via overlay network, Services via ClusterIP |
| **Scaling** | Replicas defined in compose | Pods managed by Deployments; horizontal scaling via replicas field |
| **Configuration** | Environment variables, files mounted from host | ConfigMaps, Secrets, volumes |
| **Health Checks** | Healthcheck stanzas | Liveness/Readiness probes |
| **Persistent Data** | Named volumes | PersistentVolumeClaims or emptyDir |

---

## 📚 Kubernetes Concepts Explained

### 1. **Namespace**
A logical partition within the cluster. We use `graphql-lb` to isolate our application.
```yaml
# All manifests specify:
metadata:
  namespace: graphql-lb
```
Benefits: resource quotas, RBAC policies, clean organization.

### 2. **Pod**
Smallest unit in Kubernetes; usually one container per pod (but can have multiple). Pods are ephemeral—they are created and destroyed by Deployments.

### 3. **Deployment**
Manages a set of Pods. Specifies:
- How many replicas (desired state)
- Which image to run
- Restart policy
- Health probes

Example: `graphql-server` Deployment ensures 4 pod replicas are always running.

### 4. **Service**
Abstracts access to Pods. There are three types we use:

**ClusterIP** (default)
- Internal DNS name: `graphql-server.graphql-lb.svc.cluster.local`
- Accessible only from within the cluster
- Used by: Nginx → GraphQL servers, Prometheus → pods

**NodePort**
- Exposes service on a high port (30000–32767) on each node
- Maps to localhost via kind config
- Used by: External access to Nginx, Prometheus, Grafana

### 5. **ConfigMap**
Stores configuration as key-value pairs, mounted as files or env vars.
- `nginx-config`: Contains `/etc/nginx/nginx.conf`
- `prometheus-config`: Contains scrape configurations
- `grafana-provisioning`: Contains datasources and dashboards

### 6. **ServiceAccount & RBAC**
Prometheus needs permission to query Kubernetes API for pod discovery.
- `ServiceAccount`: Identity for Prometheus Pod
- `ClusterRole`: Defines permissions (read pods, services, endpoints)
- `ClusterRoleBinding`: Grants the role to the service account

---

## 🔧 Detailed Component Breakdown

### GraphQL Servers (4 replicas)

**Deployment: `manifests/04-graphql-server.yaml`**

```yaml
spec:
  replicas: 4
  template:
    metadata:
      labels:
        app: graphql-server
        scrape: "true"  # Picked up by Prometheus
    spec:
      containers:
        - name: graphql-server
          image: auto-throttling-network-server:latest
          imagePullPolicy: Never  # Use local image
          env:
            - name: SERVER_ID
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name  # Uses pod name as server ID
```

**Key Points:**
- Each pod gets a unique name: `graphql-server-0`, `graphql-server-1`, etc.
- Pod name automatically becomes the SERVER_ID environment variable
- All pods have label `scrape: "true"`, which Prometheus uses to auto-discover them
- ClusterIP Service `graphql-server` load-balances across all 4 pods

**Health Probes:**
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10  # Give app time to start
  periodSeconds: 10        # Check every 10s
  failureThreshold: 3      # Restart after 3 failed checks

readinessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 5
  failureThreshold: 2      # Take out of rotation after 2 failures
```

If a pod's `/health` endpoint returns non-2xx, Kubernetes either restarts it (liveness) or stops routing traffic to it (readiness).

---

### Nginx Load Balancer

**Deployment: `manifests/05-nginx.yaml`**

Single-replica Nginx pod configured via ConfigMap:

```yaml
volumeMounts:
  - name: nginx-config
    mountPath: /etc/nginx/nginx.conf
    subPath: nginx.conf
    readOnly: true
volumes:
  - name: nginx-config
    configMap:
      name: nginx-config
```

The ConfigMap contains the full nginx.conf. Key difference from docker-compose:

**Original upstream:**
```nginx
server server-1:8000;
server server-2:8000;
server server-3:8000;
server server-4:8000;
```

**Kubernetes upstream (in ConfigMap):**
```nginx
upstream graphql_backends {
    least_conn;
    server graphql-server:8000;  # Single entry, Kubernetes Service handles load-balancing
    keepalive 32;
}
```

Why? Kubernetes Service DNS automatically resolves to all pod IPs. No need to list servers individually.

**NodePort Service:**
```yaml
spec:
  type: NodePort
  ports:
    - port: 80              # Service IP port
      targetPort: http      # Pod port
      nodePort: 30080       # External node port
```

Access flow:
1. User hits `localhost:8080` (kind port mapping)
2. Kind maps to NodePort `30080` on the cluster node
3. Service routes to Nginx Pod
4. Nginx proxies to `graphql-server` Service
5. Service round-robins across 4 GraphQL server pods

---

### Prometheus with Service Discovery

**Deployment: `manifests/07-prometheus.yaml`**

Prometheus is configured with **Kubernetes Service Discovery** instead of static targets:

```yaml
scrape_configs:
  - job_name: 'kubernetes-pods'
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
            - graphql-lb
    relabel_configs:
      # Only scrape pods with label scrape: "true"
      - source_labels: [__meta_kubernetes_pod_label_scrape]
        action: keep
        regex: "true"
      # Extract pod labels and make them Prometheus labels
      - source_labels: [__meta_kubernetes_pod_label_app]
        action: replace
        target_label: app
      - source_labels: [__meta_kubernetes_pod_name]
        action: replace
        target_label: pod
```

**How it works:**
1. Prometheus queries Kubernetes API for all pods in `graphql-lb` namespace
2. Filters pods with label `scrape: "true"`
3. Automatically discovers pod IPs and port 8000
4. Scrapes `/metrics` every 5 seconds
5. If a pod is added/removed, Prometheus auto-discovers it (within 5s)

This is far more powerful than static configs—no manual server list needed!

**RBAC Setup (in `00-rbac.yaml`):**
```yaml
serviceAccountName: prometheus

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: graphql-lb-reader
rules:
  - apiGroups: [""]
    resources: ["pods", "services", "endpoints", "nodes"]
    verbs: ["get", "list", "watch"]

---
kind: ClusterRoleBinding
metadata:
  name: graphql-lb-reader
roleRef:
  kind: ClusterRole
  name: graphql-lb-reader
subjects:
  - kind: ServiceAccount
    name: prometheus
    namespace: graphql-lb
```

The ClusterRole grants Prometheus read access to pod metadata. Without this, the API calls fail.

---

### Load Generator Client

**Deployment: `manifests/06-client.yaml`**

```yaml
spec:
  replicas: 1
  template:
    spec:
      restartPolicy: Always
      containers:
        - name: graphql-client
          image: auto-throttling-network-client:latest
          imagePullPolicy: Never
          env:
            - name: NGINX_URL
              value: "http://nginx/graphql"
```

Key point: `NGINX_URL` uses Kubernetes DNS name `nginx`. This resolves to the ClusterIP Service, which routes to the Nginx Pod.

The client loops forever sending requests, just like in docker-compose. Logs can be viewed with:
```bash
kubectl logs -f -n graphql-lb deployment/graphql-client
```

---

### Grafana Dashboard Provisioning

**ConfigMap: `manifests/09-grafana-provisioning.yaml`**

Contains three files:

1. **datasources.yml** — Tells Grafana where Prometheus lives:
   ```yaml
   datasources:
     - name: Prometheus
       type: prometheus
       url: http://prometheus:9090  # Kubernetes DNS
   ```

2. **dashboards.yml** — Points to dashboard JSON files in `/etc/grafana/provisioning/dashboards`

3. **nginx-lb-demo.json** — Pre-built dashboard with panels:
   - Requests/s by server
   - Server load %
   - Latency percentiles (P50, P95)
   - Active in-flight requests

Grafana auto-loads these on startup via volume mounts.

---

## 🔍 How Service Discovery Works

### Kubernetes DNS

Every Service creates DNS entries:
- **Short name:** `nginx` (within namespace) → resolves to ClusterIP
- **Full name:** `nginx.graphql-lb.svc.cluster.local` (from anywhere)

Example: When Nginx Pod needs to connect to GraphQL servers:
```nginx
upstream graphql_backends {
    server graphql-server:8000;  # Short name within same namespace
}
```

Kubernetes DNS resolves `graphql-server` → Service ClusterIP (e.g., 10.96.0.5)
Service load-balances across all backend pods.

### Pod-to-Pod Communication

```
Nginx Pod                    Service (10.96.0.5)         Pod IPs
┌──────────────┐            ┌──────────────────┐        ┌─────────┐
│ 10.244.0.2   │────────→   │ graphql-server   │───────→│10.244.0.3│ (graphql-server-0)
│ (nginx)      │            │ (ClusterIP)      │        └─────────┘
└──────────────┘            │ (iptables rules) │        ┌─────────┐
                            │  round-robin     │───────→│10.244.0.4│ (graphql-server-1)
                            └──────────────────┘        └─────────┘
                                                         ┌─────────┐
                                                    ────→│10.244.0.5│ (graphql-server-2)
                                                         └─────────┘
                                                         ┌─────────┐
                                                    ────→│10.244.0.6│ (graphql-server-3)
                                                         └─────────┘
```

Kubernetes uses iptables rules on the node to intercept traffic to the Service IP and distribute it.

---

## 🎬 Running & Monitoring

### Watch Pod Status

```bash
# All pods
kubectl get pods -n graphql-lb -w

# Specific deployment
kubectl get deployment -n graphql-lb graphql-server
```

### View Logs

```bash
# Client logs (shows request routing)
kubectl logs -f -n graphql-lb deployment/graphql-client

# Nginx logs
kubectl logs -f -n graphql-lb deployment/nginx

# GraphQL server logs
kubectl logs -f -n graphql-lb deployment/graphql-server

# Single pod
kubectl logs -f -n graphql-lb graphql-server-0
```

### Scale Servers Up/Down

```bash
# Increase to 6 replicas
kubectl scale deployment graphql-server --replicas=6 -n graphql-lb

# Back to 4
kubectl scale deployment graphql-server --replicas=4 -n graphql-lb

# Watch scaling happen
kubectl get pods -n graphql-lb -w
```

### Exec into a Pod

```bash
# Run a shell inside a pod
kubectl exec -it -n graphql-lb graphql-server-0 -- sh

# Run a quick command
kubectl exec -n graphql-lb graphql-server-0 -- curl http://localhost:8000/health
```

### Port Forwarding (Alternative to NodePort)

```bash
# Forward local port 8000 to Nginx service port 80
kubectl port-forward -n graphql-lb svc/nginx 8000:80

# Forward Prometheus
kubectl port-forward -n graphql-lb svc/prometheus 9090:9090
```

Then access via `localhost:8000`, `localhost:9090`, etc.

### Check Resource Usage

```bash
kubectl top nodes                    # Node usage
kubectl top pods -n graphql-lb       # Pod usage (requires metrics-server)
```

---

## 🐛 Troubleshooting

### Pods Not Starting

```bash
# Check pod status and events
kubectl describe pod -n graphql-lb graphql-server-0

# Common issues:
# - ImagePullBackOff: Image not loaded. Run:
#   kind load docker-image auto-throttling-network-server:latest --name graphql-lb

# - Pending: Usually waiting for resources. Check:
#   kubectl get nodes
#   kubectl describe node <node-name>
```

### Service Not Reachable

```bash
# Check service endpoints
kubectl get endpoints -n graphql-lb

# Should show pod IPs for graphql-server:
# NAME             ENDPOINTS
# graphql-server   10.244.0.3:8000,10.244.0.4:8000,10.244.0.5:8000,10.244.0.6:8000

# If empty, pods aren't ready (check describe pod)

# Test DNS from within cluster
kubectl exec -it -n graphql-lb nginx-0 -- nslookup graphql-server
```

### Nginx Can't Reach Backends

```bash
# SSH into Nginx pod
kubectl exec -it -n graphql-lb deployment/nginx -- sh

# Try curl to GraphQL service
curl http://graphql-server:8000/health

# Check nginx config is loaded
cat /etc/nginx/nginx.conf

# Check nginx logs
tail -f /var/log/nginx/error.log
```

### Prometheus Not Scraping Pods

```bash
# Check Prometheus config
kubectl exec -it -n graphql-lb deployment/prometheus -- cat /etc/prometheus/prometheus.yml

# Check targets in Prometheus UI
# http://localhost:9090/targets

# Look for "kubernetes-pods" job and verify pods are listed

# Check ServiceAccount permissions
kubectl get clusterrolebinding graphql-lb-reader -o yaml
```

### Client Not Sending Requests

```bash
kubectl logs -n graphql-lb deployment/graphql-client

# Common error: "can't connect to remote host"
# Means nginx service not reachable. Check:
kubectl get svc -n graphql-lb
kubectl exec -it -n graphql-lb graphql-client-0 -- curl http://nginx/ping
```

### ConfigMap Changes Not Reflected

ConfigMaps are mounted as volumes. Changes require a pod restart:

```bash
# After editing ConfigMap
kubectl rollout restart deployment/nginx -n graphql-lb
kubectl rollout restart deployment/prometheus -n graphql-lb
```

---

## 🧹 Cleanup

### Delete Everything

```bash
# Delete namespace (cascades to all resources)
kubectl delete namespace graphql-lb

# Delete Kind cluster
kind delete cluster --name graphql-lb
```

### Partial Cleanup

```bash
# Delete specific deployment (pods will be recreated by replicaset)
kubectl delete deployment graphql-server -n graphql-lb

# Delete pods (Deployment recreates them)
kubectl delete pod graphql-server-0 -n graphql-lb

# Delete service (keeps pods, just stops exposing them)
kubectl delete service nginx -n graphql-lb
```

---

## 📊 Advanced Topics (Optional)

### Horizontal Pod Autoscaling

Create an HPA to scale based on CPU:
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: graphql-server-hpa
  namespace: graphql-lb
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: graphql-server
  minReplicas: 2
  maxReplicas: 8
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

Apply with: `kubectl apply -f hpa.yaml`

### Multi-Node Cluster

To test Pod scheduling across nodes:
```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
  - role: worker
  - role: worker
```

Then `kind create cluster --config cluster-3-node.yaml`.

### PersistentVolumes for Prometheus/Grafana Data

Replace `emptyDir: {}` with:
```yaml
volumes:
  - name: prometheus-storage
    persistentVolumeClaim:
      claimName: prometheus-pvc
```

And create a PVC:
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: prometheus-pvc
  namespace: graphql-lb
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
```

---

## 🎓 Learning Outcomes

After completing this setup, you'll understand:

1. **Kubernetes fundamentals**: Pods, Deployments, Services, ConfigMaps
2. **Service discovery**: How DNS and iptables route traffic between pods
3. **Load balancing**: Nginx + Kubernetes Service load-balancing interaction
4. **Monitoring at scale**: Kubernetes service discovery for Prometheus
5. **Operational concerns**: Health probes, scaling, troubleshooting
6. **Docker → K8s migration**: How to translate docker-compose to manifests

---

## 📖 References

- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [Kind Documentation](https://kind.sigs.k8s.io/)
- [Prometheus Kubernetes SD](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#kubernetes_sd_config)
- [Nginx Upstream Load Balancing](https://nginx.org/en/docs/http/load_balancing.html)

---

**Happy learning! 🚀**
