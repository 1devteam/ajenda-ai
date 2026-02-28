# 5. Scaling

## Horizontal Scaling

The backend is stateless and can be scaled horizontally by increasing the number of replicas in the `deployment.yaml` file. The Horizontal Pod Autoscaler (HPA) is also configured to automatically scale the deployment based on CPU utilization.

## Vertical Scaling

To scale vertically, adjust the `resources` section in the `deployment.yaml` to allocate more CPU or memory to the pods.