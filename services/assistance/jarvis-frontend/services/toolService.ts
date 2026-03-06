import { GoogleGenAI } from "@google/genai";
import { GroundingSource } from "../types";

// Initialize standard client for tool execution
const getClient = () => new GoogleGenAI({ apiKey: process.env.API_KEY });

export async function performSearch(query: string): Promise<{ text: string; sources: GroundingSource[] }> {
  try {
    const ai = getClient();
    const response = await ai.models.generateContent({
      model: "gemini-2.5-flash",
      contents: query,
      config: {
        tools: [{ googleSearch: {} }],
      },
    });

    const text = response.text || "I found some information.";
    
    // Extract grounding chunks
    const chunks = response.candidates?.[0]?.groundingMetadata?.groundingChunks || [];
    const sources: GroundingSource[] = chunks
      .map((chunk: any) => chunk.web)
      .filter((web: any) => web && web.uri && web.title)
      .map((web: any) => ({
        title: web.title,
        uri: web.uri,
      }));

    return { text, sources };
  } catch (error) {
    console.error("Search error:", error);
    return { text: "I'm sorry, I encountered an error while searching.", sources: [] };
  }
}

export async function generateImage(prompt: string): Promise<{ imageUrl: string | null; error?: string }> {
  console.log("Generating image with prompt:", prompt);
  try {
    const ai = getClient();
    // Using Nano Banana Pro for high quality images
    const response = await ai.models.generateContent({
      model: "gemini-3-pro-image-preview",
      contents: prompt,
      config: {
        imageConfig: {
          aspectRatio: "16:9",
          imageSize: "1K"
        }
      }
    });

    for (const part of response.candidates?.[0]?.content?.parts || []) {
      if (part.inlineData) {
        console.log("Image generation successful");
        return { imageUrl: `data:image/png;base64,${part.inlineData.data}` };
      }
    }
    console.warn("No image data in response", response);
    return { imageUrl: null, error: "No image data received." };
  } catch (error) {
    console.error("Image generation error:", error);
    return { imageUrl: null, error: "Failed to generate image." };
  }
}

export async function reimagineImage(base64Image: string, prompt: string): Promise<{ imageUrl: string | null; error?: string }> {
  console.log("Reimagining image with prompt:", prompt);
  try {
    const ai = getClient();
    const response = await ai.models.generateContent({
      model: "gemini-3-pro-image-preview",
      contents: {
        parts: [
          {
            inlineData: {
              mimeType: "image/jpeg",
              data: base64Image
            }
          },
          { text: prompt }
        ]
      },
      config: {
        imageConfig: {
            aspectRatio: "16:9",
            imageSize: "1K"
        }
      }
    });

    for (const part of response.candidates?.[0]?.content?.parts || []) {
      if (part.inlineData) {
        console.log("Reimagine successful");
        return { imageUrl: `data:image/png;base64,${part.inlineData.data}` };
      }
    }
    console.warn("No reimagine data in response", response);
    return { imageUrl: null, error: "No image data received." };

  } catch (error) {
    console.error("Reimagine error:", error);
    return { imageUrl: null, error: "Failed to reimagine image." };
  }
}