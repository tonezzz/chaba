# Jarvis Modularization Guide

## Quick Start

This guide helps you understand and work with the newly modularized Jarvis codebase.

## What Changed

### Backend Structure
```
jarvis-backend/
├── main.py              # Original monolith (813K lines) - still works
├── main_new.py          # NEW: Modular reference implementation
└── jarvis/              # NEW: Modular package
    ├── agents/          # Agent discovery and dispatch
    ├── skills/          # Deterministic skills (news, etc.)
    ├── websocket/       # Session management
    ├── mcp/             # Tool routing and caching
    ├── memory/          # Cache management
    ├── api/             # HTTP route modules
    └── utils/           # Shared utilities
```

### Frontend Structure
```
jarvis-frontend/
├── App.tsx              # Original monolith - still works
└── components/          # Enhanced with modular components
    ├── chat/            # NEW: MessageInput component
    ├── debug/           # NEW: DebugPanel component
    └── services/         # Enhanced with modular services
        └── websocket/   # NEW: WebSocketClient service
```

## How to Test the Modular Version

### 1. Test the mcp-news Integration
```bash
# Deploy isolated test stack
docker-compose -f stacks/idc1-assistance-test/docker-compose.yml up -d

# Verify it's working
curl http://127.0.0.1:3151/health

# Test mcp-news tools
curl -X POST http://127.0.0.1:3151/tools/list | jq '.tools[] | select(.name | contains("news"))'
```

### 2. Test the Modular Backend
```bash
# When ready to test modular backend
cd services/assistance/jarvis-backend

# Backup original
cp main.py main.py.backup

# Use modular version
cp main_new.py main.py

# Restart service and test
curl http://127.0.0.1:8000/jarvis/api/debug/status
```

### 3. Test Modular Frontend Components
```typescript
// In your App.tsx, gradually import modular components
import { MessageInput } from './components/chat/MessageInput';
import { DebugPanel } from './components/debug/DebugPanel';
import { WebSocketClient } from './services/websocket/WebSocketClient';

// Replace existing components gradually
```

## Adding New Features

### Backend: Add New API Endpoint
```python
# 1. Create new module: jarvis/api/feature.py
from fastapi import APIRouter
from jarvis.utils.validation import require_api_token_if_configured

router = APIRouter()

@router.post("/feature/action")
async def feature_action(
    req: dict[str, Any],
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    require_api_token_if_configured(x_api_token)
    # Your logic here
    return {"ok": True, "result": "success"}

# 2. Add to main_new.py
from jarvis.api.feature import router as feature_router
app.include_router(feature_router, prefix="/jarvis/api", tags=["feature"])
```

### Backend: Add New Skill
```python
# 1. Create: jarvis/skills/feature.py
class FeatureSkill:
    async def handle_feature(self, ws: WebSocket, text: str, trace_id: str) -> bool:
        # Your skill logic here
        return True

# 2. Export in jarvis/skills/__init__.py
from .feature import FeatureSkill
```

### Frontend: Add New Component
```typescript
// 1. Create: components/feature/FeatureComponent.tsx
interface FeatureComponentProps {
  onAction: (data: any) => void;
  disabled?: boolean;
}

export default function FeatureComponent({ onAction, disabled }: FeatureComponentProps) {
  // Component logic here
}

// 2. Import in App.tsx
import FeatureComponent from './components/feature/FeatureComponent';
```

## Migration Checklist

### Before Migration to Modular
- [ ] Test stack deployed and working
- [ ] All mcp-news tools functional
- [ ] Modular backend tested locally
- [ ] Frontend components tested in isolation

### Migration Steps
1. **Backend Migration**:
   ```bash
   # Backup production main.py
   cp main.py main.py.production
   
   # Deploy modular version
   cp main_new.py main.py
   docker-compose restart jarvis-backend
   
   # Verify all endpoints work
   curl http://127.0.0.1:8000/jarvis/api/debug/status
   ```

2. **Frontend Migration**:
   ```typescript
   // Gradually replace components in App.tsx
   // Start with non-critical components first
   ```

3. **Production Stack Update**:
   ```yaml
   # Add mcp-news to production when ready
   volumes:
     - ../../mcp/mcp-news:/app/mcp-servers/mcp-news:ro
     - mcp-news-data:/data/mcp-news
   ```

### Post-Migration Verification
- [ ] All existing functionality works
- [ ] New modular features functional
- [ ] Performance unchanged or improved
- [ ] Error rates normal

## Troubleshooting

### Common Issues

#### Import Errors
```python
# Error: ModuleNotFoundError: No module named 'jarvis.api.memo'
# Solution: Ensure PYTHONPATH includes the jarvis package
export PYTHONPATH=$PYTHONPATH:/path/to/jarvis-backend
```

#### TypeScript Errors
```typescript
// Error: Cannot find module './components/chat/MessageInput'
// Solution: Check file paths and ensure .tsx extension
import MessageInput from './components/chat/MessageInput.tsx';
```

#### WebSocket Connection Issues
```bash
# Error: WebSocket connection failed
# Solution: Check ports and network configuration
# Production: 3051, Test: 3151
```

#### mcp-news Not Available
```bash
# Error: mcp-news tools not in tools/list
# Solution: Verify volume mounts and dist/ directory exists
docker exec mcp-bundle-test ls /app/mcp-servers/mcp-news/dist/
```

### Debug Commands
```bash
# Check backend logs
docker-compose logs jarvis-backend

# Check mcp-bundle logs
docker-compose logs mcp-bundle-test

# Test WebSocket connection
wscat -c ws://127.0.0.1:3151/ws/live?session_id=test

# Verify API endpoints
curl -X GET http://127.0.0.1:3151/tools/list
```

## Best Practices

### Code Organization
- Keep modules focused on single responsibility
- Use clear naming conventions
- Add type hints and documentation
- Write tests for new modules

### Testing
- Test modules in isolation
- Use the test stack for integration testing
- Verify production compatibility before migration

### Performance
- Monitor memory usage with new modules
- Check WebSocket connection handling
- Validate API response times

## Rollback Plan

If issues arise during migration:

### Quick Rollback
```bash
# Restore original main.py
cp main.py.production main.py
docker-compose restart jarvis-backend
```

### Complete Rollback
```bash
# Remove test stack
docker-compose -f stacks/idc1-assistance-test/docker-compose.yml down

# Restore original files
git checkout main.py
git checkout App.tsx
```

## Support

For questions about the modularization:
1. Check this guide first
2. Review the strategy document: `docs/MODULARIZATION_STRATEGY.md`
3. Test in isolated environment first
4. Gradual migration is recommended

## Future Enhancements

The modular structure enables:
- **Microservices**: Individual modules can be extracted
- **Team development**: Different teams can own different modules
- **A/B testing**: New features can be tested in isolation
- **Performance optimization**: Modules can be optimized independently

This foundation makes Jarvis more maintainable and scalable for future development.
