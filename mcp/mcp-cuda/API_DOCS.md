# MCP-CUDA API Documentation

## Available Tools

### Image Generation
- `imagen_job_create`: Create new image generation job
- `imagen_job_status`: Check job status

### System Info
- `cuda_info`: Get CUDA/GPU information
- `torch_info`: Get PyTorch information

## Example Requests

```json
{
  "tool": "imagen_job_create",
  "arguments": {
    "prompt": "A beautiful landscape",
    "width": 512,
    "height": 512
  }
}
```
