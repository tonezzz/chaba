# Architecture

## Overview

Jarvis is a real-time, multimodal AI assistant built with React and the Google GenAI SDK. It integrates live audio and video streaming with advanced AI capabilities, including real-time conversation, internet search, and image generation. The application mimics a futuristic "Jarvis-like" interface, providing immediate visual and auditory feedback.

## Tech Stack

- **Frontend Framework**: React 18 with TypeScript
- **Build Tool**: Vite
- **Styling**: Tailwind CSS with custom animations
- **AI Integration**: Google GenAI SDK (`@google/genai`)
- **Icons**: Lucide React

## Core Architecture

The application is architected around a central `LiveService` that manages the persistent connection to the Google Gemini API. The frontend components react to state changes driven by this service.

### 1. Service Layer

#### `LiveService` (`services/liveService.ts`)
This is the heart of the application. It handles:
- **Connection Management**: Establishes and maintains the WebSocket/WebRTC session with the Gemini model (`gemini-2.5-flash-native-audio-preview-09-2025`).
- **Audio Processing**: 
  - Captures microphone input using `AudioContext` and `ScriptProcessorNode`.
  - Converts audio data to PCM16 format for the model.
  - Plays back response audio from the model.
- **Video Processing**: Receives camera frames and transmits them as real-time input to the model to provide vision capabilities.
- **Tool Execution**: Intercepts function calls from the model (e.g., search, image generation) and delegates them to the `ToolService`.

#### `ToolService` (`services/toolService.ts`)
Handles the execution of specific tools requested by the AI model:
- **Search**: Uses `gemini-2.5-flash` with the `googleSearch` tool to retrieve real-time information.
- **Image Generation**: Uses (Nano Banana Pro) `gemini-3-pro-image-preview` to generate images from text prompts.
- **Image Reimagination**: Uses (Nano Banana Pro) `gemini-3-pro-image-preview` to modify or "reimagine" the user's camera feed based on a prompt.

### 2. Frontend Components

- **`App.tsx`**: The main controller component. It initializes the `LiveService`, manages global state (connection status, volume, message logs), and orchestrates the UI layout.
- **`components/CameraFeed.tsx`**: Manages the webcam video stream. It extracts frames at a regular interval to send to the AI model.
- **`components/Visualizer.tsx`**: Renders a real-time audio visualizer based on the volume levels provided by the `LiveService`.

## Data Flow

1.  **Initialization**: The user provides an API key (via `aistudio` injection or selection).
2.  **Connection**: `LiveService` connects to the Gemini Multimodal Live API.
3.  **Input Loop**:
    - **Audio**: Microphone data is constantly buffered, converted, and streamed to the model.
    - **Video**: `CameraFeed` captures frames, which `LiveService` sends as image data chunks.
4.  **Model Processing**: The Gemini model processes the audio and visual inputs in context.
5.  **Output Loop**:
    - **Audio Response**: The model streams audio chunks back, which are queued and played by `LiveService`.
    - **Tool Calls**: If the model determines a tool is needed (e.g., "draw a cat"), it sends a function call. `LiveService` executes the function via `ToolService`, sends the result back to the model, and updates the UI (e.g., displaying the generated image).

## Directory Structure

- `components/`: UI components for visualization and camera management.
- `services/`: Core business logic and AI integration services.
- `docs/`: Project documentation.
- `types.ts`: TypeScript definitions for application interfaces and data structures.
