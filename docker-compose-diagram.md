# Docker Compose Architecture Diagram

```mermaid
graph TB
    %% Host System
    subgraph "Host System"
        GPU[NVIDIA GPU]
        Data[./data]
        Outputs[./outputs]
        Notebooks[./notebooks]
        Src[./src/gaussian-splatting]
        X11[/tmp/.X11-unix]
    end

    %% Docker Services
    subgraph "Docker Compose Services"
        %% Base Image (build only)
        Base[base<br/> gaussian-splatting-base:latest<br/>Build Only]
        
        %% COLMAP Service
        COLMAP[colmap<br/> gaussian-splatting-colmap:latest<br/>Structure-from-Motion]
        
        %% 3DGS Service
        D3GS[3dgs<br/> gaussian-splatting-3dgs:latest<br/>Original 3DGS<br/>graphdeco-inria]
        
        %% Nerfstudio Service
        Nerfstudio[nerfstudio<br/> gaussian-splatting-nerfstudio:latest<br/>Nerfstudio + gsplat<br/>Port: 7007]
        
        %% Variants Service
        Variants[variants<br/> gaussian-splatting-variants:latest<br/>2DGS | Mip-Splatting | GOF]
        
        %% John Service
        John[john<br/> gaussian-splatting-john:latest<br/>John the Ripper]
        
        %% Jupyter Service
        Jupyter[jupyter<br/> gaussian-splatting-base:latest<br/>Jupyter Lab<br/>Port: 8888]
    end

    %% GPU Connections
    GPU -.-> COLMAP
    GPU -.-> D3GS
    GPU -.-> Nerfstudio
    GPU -.-> Variants
    GPU -.-> Jupyter

    %% Volume Connections
    Data --> COLMAP
    Data --> D3GS
    Data --> Nerfstudio
    Data --> Variants
    Data --> John
    Data --> Jupyter

    Outputs --> COLMAP
    Outputs --> D3GS
    Outputs --> Nerfstudio
    Outputs --> Variants
    Outputs --> John
    Outputs --> Jupyter

    %% Special Volume Connections
    Src -.-> D3GS
    Notebooks -.-> Jupyter
    X11 -.-> D3GS

    %% Service Dependencies (implicit)
    Base --> COLMAP
    Base --> D3GS
    Base --> Nerfstudio
    Base --> Variants
    Base --> John
    Base --> Jupyter

    %% Styling
    classDef gpuService fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    classDef cpuService fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    classDef baseService fill:#fff3e0,stroke:#e65100,stroke-width:2px
    classDef hostResource fill:#e8f5e8,stroke:#2e7d32,stroke-width:2px

    class COLMAP,D3GS,Nerfstudio,Variants,Jupyter gpuService
    class John cpuService
    class Base baseService
    class GPU,Data,Outputs,Notebooks,Src,X11 hostResource
```

## Service Overview

### GPU-Accelerated Services
- **colmap**: Structure-from-Motion preprocessing with GPU support
- **3dgs**: Original 3D Gaussian Splatting implementation (graphdeco-inria)
- **nerfstudio**: Nerfstudio with gsplat integration, web viewer on port 7007
- **variants**: Extended variants (2DGS, Mip-Splatting, GOF)
- **jupyter**: Jupyter Lab environment with GPU support, accessible on port 8888

### CPU-Only Services
- **john**: John the Ripper password recovery tool
- **base**: Base image used for building other services (build-only)

### Shared Resources
- **Volumes**: All services share `./data` and `./outputs` directories
- **GPU Access**: NVIDIA GPU with full driver capabilities
- **Network**: Nerfstudio (7007) and Jupyter (8888) expose web interfaces

### Development Features
- **3dgs** has optional source code mounting for development
- **3dgs** supports X11 forwarding for the SIBR viewer
- **Jupyter** includes notebook workspace for experiments
