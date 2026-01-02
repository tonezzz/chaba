import { Plugin, PluginID } from '@/types/plugin';

export const getEndpoint = (plugin: Plugin | null) => {
  const basePath = (process.env.NEXT_PUBLIC_BASE_PATH || '').trim().replace(/\/+$/, '');
  const prefix = basePath ? `${basePath}/` : '';
  if (!plugin) {
    return `${prefix}api/chat`;
  }

  if (plugin.id === PluginID.GOOGLE_SEARCH) {
    return `${prefix}api/google`;
  }

  return `${prefix}api/chat`;
};
