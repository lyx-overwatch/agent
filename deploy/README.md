# deploy 部署说明

## 常驻沙箱池（resident sandbox pool）轮换

### 背景

多用户共用常驻沙箱池（`pool-0` … `pool-N-1`）。同一个 Pod 会被不同租户先后
复用，上一租户可能在 `/mnt/user-data`、`/tmp`、`HOME` 乃至系统目录留下文件——
既是用户隐私泄露风险，也是恶意写入系统文件的风险。

轮换 = 销毁旧 Pod 重建全新 Pod（全新容器文件系统 + 全新 emptyDir），从根源上
一次性清掉上一租户的所有写入。

### 两个机制（删 / 建分离）

- **删**：`sandbox-pool-rotate-cronjob.yaml`（CronJob）每天 CST 凌晨 2:00 用
  label selector 删除所有 `sandbox-resident=true` 的 Pod **和** Service。
- **建**：provisioner 的 `_resident_pool_health_loop` 每 60s 巡检一轮，发现
  Service 缺失就立即 `_ensure_resident_sandbox` 重建（幂等）。

因为 CronJob 同时删了 Pod + Service，重建只需**单轮巡检（≤60s）**。

### CronJob 镜像准备（一次性）

`bitnami/kubectl` 已从 Docker Hub 下架（Bitnami 2025-08 目录迁移），且 CCE 节点
拉不到公开 Docker Hub。所以自建一个「alpine + kubectl 二进制」极简镜像推到内网
SWR，Dockerfile 在 `deploy/kubectl-rotate/Dockerfile`：

```bash
cd deploy/kubectl-rotate
docker build -t swr.cn-south-1.myhuaweicloud.com/fintech-aigc/kubectl:1.32.3 \
  --build-arg KUBECTL_VERSION=v1.32.3 .
docker login swr.cn-south-1.myhuaweicloud.com
docker push swr.cn-south-1.myhuaweicloud.com/fintech-aigc/kubectl:1.32.3
```

> 版本号与 CronJob 里的 `image:` tag（`1.32.3`）保持一致即可。**entrypoint 无关**：
> CronJob 用的是 `command`（对应 Docker 的 ENTRYPOINT），会整体覆盖镜像里的
> ENTRYPOINT/CMD，所以只要 `kubectl` 在 PATH 里就能跑，不需要特殊入口脚本。

### ⚠️ Service label 的坑（部署顺序）

`_build_service(resident=True)` 给 resident Service 打的 `sandbox-resident`
label **只在创建时生效**。旧代码创建的 resident Service（如 `sandbox-pool-0-svc`）
**没有**这个 label。

如果直接重新部署 provisioner 就上线 CronJob，凌晨删的时候
`kubectl delete svc -l sandbox-resident=true` 会**删不到旧 Service**（它们没
label），只有 Pod 被删 → 又退回两轮（~120s）。

**正确部署顺序：**

1. 部署新 provisioner。
2. 手动删一次旧 resident Service，让巡检用新代码重建出带 label 的 Service：

   ```bash
   kubectl delete svc -n fintech-aigc-dev sandbox-pool-0-svc sandbox-pool-1-svc sandbox-pool-2-svc
   ```

   （`SANDBOX_POOL_SIZE` 变了就按实际 slot 数量删对应名字）

3. 确认新 Service 已带上 label：

   ```bash
   kubectl get svc -n fintech-aigc-dev -l sandbox-resident=true
   ```

4. 再应用 CronJob：

   ```bash
   kubectl apply -f deploy/sandbox-pool-rotate-cronjob.yaml
   ```

### 手动验证脚本

```bash
# 观察当前池子
kubectl get pod,svc -n fintech-aigc-dev -l sandbox-resident=true

# 删 Pod + Service（模拟 CronJob 行为；新 Service 带 label 后可整条按 label 删）
kubectl delete pod,svc -n fintech-aigc-dev -l sandbox-resident=true

# 等 ≤60s，观察是否自动重建出新 Pod + Service（AGE 归零）
kubectl get pod,svc -n fintech-aigc-dev -l sandbox-resident=true
```

> 只删 Pod、不删 Service 时，重建需要**两轮巡检（~120s）**：第一轮发现 Pod
> missing → 删 Service，第二轮发现 Service missing → 重建。
