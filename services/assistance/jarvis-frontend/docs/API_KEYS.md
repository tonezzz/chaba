# Google GenAI API Keys & Configuration

To run this application, you need to configure the Google GenAI SDK with valid credentials. You can use either the **Gemini Developer API** (Google AI Studio) or the **Vertex AI Gemini API** (Google Cloud Platform).

## 1. Gemini Developer API (Google AI Studio)

The Gemini Developer API is the fastest way to get started. It's ideal for prototyping and individual developers.

### Setup
1.  Go to [Google AI Studio](https://aistudio.google.com/).
2.  Create an API Key.
3.  Set the `API_KEY` environment variable in your project.

### Code Example
When using the Gemini Developer API, initialization is simple:

```typescript
import { GoogleGenAI } from "@google/genai";

const ai = new GoogleGenAI({ 
  apiKey: process.env.API_KEY 
});

// Example usage
async function main() {
  const response = await ai.models.generateContent({
    model: "gemini-2.0-flash",
    contents: "Explain how AI works in a few words",
  });
  console.log(response.text);
}
```

## 2. Vertex AI Gemini API (Google Cloud Platform)

Vertex AI offers an enterprise-ready environment with additional controls, security, and scalability features backed by Google Cloud Platform (GCP). **This is the recommended approach for production deployments.**

### Setup
1.  Create a Google Cloud Project.
2.  Enable the **Vertex AI API**.
3.  Ensure you have a Service Account with appropriate permissions or are authenticated via `gcloud auth`.

### Code Example
To use Vertex AI, you must configure the SDK with your project details and set `vertexai: true`.

```typescript
import { GoogleGenAI } from '@google/genai';

const ai = new GoogleGenAI({
  vertexai: true,
  project: 'your_project_id',
  location: 'us-central1', // e.g., us-central1
  // You may also need to provide GoogleAuth credentials if not using default environment auth
});

async function main() {
  const response = await ai.models.generateContent({
    model: "gemini-2.0-flash",
    contents: "Explain how AI works in a few words",
  });
  console.log(response.text);
}
```

## Configuring the Application

The application currently initializes `GoogleGenAI` in two places:
- `services/liveService.ts`
- `services/toolService.ts`

To switch to Vertex AI, you will need to update the constructor calls in these files.

**Current (Gemini Developer API):**
```typescript
this.ai = new GoogleGenAI({ apiKey: process.env.API_KEY });
```

**For Vertex AI:**
```typescript
this.ai = new GoogleGenAI({ 
  vertexai: true,
  project: process.env.GCP_PROJECT,
  location: process.env.GCP_LOCATION
});
```

Ensure your `.env.local` or environment variables are updated accordingly:
```bash
# For Gemini Developer API
API_KEY=your_api_key_here

# For Vertex AI
GCP_PROJECT=your_project_id
GCP_LOCATION=us-central1
```

## Summary of Differences

| Feature | Gemini Developer API | Vertex AI Gemini API |
| :--- | :--- | :--- |
| **Access** | Google AI Studio | Google Cloud Platform |
| **Use Case** | Prototyping, Individual Devs | Enterprise, Production, Scalability |
| **Initialization** | `apiKey` | `vertexai: true`, `project`, `location` |
| **SDK** | `@google/genai` | `@google/genai` |

Both services are accessible through the unified `@google/genai` SDK, making migration simple.
