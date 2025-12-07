Continue = 'Stop'
 = @{
  tool = 'run_workflow'
  arguments = @{
    workflow_id = 'deploy-a1-idc1'
    dry_run = True
  }
} | ConvertTo-Json -Compress -Depth 5

 = Invoke-WebRequest -Uri 'http://127.0.0.1:8320/invoke' -Method Post -ContentType 'application/json' -Body 
.Content | Tee-Object -FilePath 'C:\chaba\temp\deploy_dryrun_response.json'
