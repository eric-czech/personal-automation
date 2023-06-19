# Configuration

To enable GCP access:

- Create a service account
    - https://cloud.google.com/iam/docs/service-accounts-create#iam-service-accounts-create-console
    - Use "Viewer" role
- Create a workload identity pool
  - `gcloud iam workload-identity-pools create github-wif-pool --location="global" --project $GCP_PROJECT`
- Add a "provider" for this pool
  - Go to https://console.cloud.google.com/iam-admin/workload-identity-pools
  - Click "Add Provider" at the top
    - Name = "Github"
    - Issuer URL = "https://token.actions.githubusercontent.com"
    - Add attribute mappings from: https://medium.com/google-cloud/how-does-the-gcp-workload-identity-federation-work-with-github-provider-a9397efd7158
      - You could also just use the CLI command mentioned there
- Add the service account to the pool
  - Click "Grant Access" at the top and choose the account
- Add the service account to this pool
  - https://console.cloud.google.com/iam-admin/workload-identity-pools
- Go to the GCS bucket bucket and add storage IAM roles for the service account
- Configure the actions step (see https://github.com/google-github-actions/upload-cloud-storage):

```yaml
- id: auth
  name: GCP Auth
  uses: google-github-actions/auth@v0.4.0
  with:
    # Get this from https://console.cloud.google.com/iam-admin/workload-identity-pools/pool/github-wif-pool/provider/github
    workload_identity_provider: 'projects/413156992799/locations/global/workloadIdentityPools/github-wif-pool/providers/github'
    service_account: 'gha-workflow@personal-analysis-388903.iam.gserviceaccount.com'
```
