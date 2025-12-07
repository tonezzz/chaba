import './main.css';

type StatusState = 'pending' | 'ok' | 'error' | 'idle';

interface CardConfig {
  chip: string;
  title: string;
  description: string;
  href?: string;
  cta?: string;
  target?: '_blank';
  status?: {
    url?: string;
    state?: StatusState;
    label?: string;
  };
}

const cards: CardConfig[] = [
  {
    chip: 'Chat',
    title: 'Glama verification console',
    description:
      'Full UI for exercising the Glama backend with temperature control and Enter-to-send toggle.',
    href: '/test/chat',
    cta: 'Open panel',
    status: { url: '/test/chat' }
  },
  {
    chip: 'Chat API',
    title: 'Proxy health + metadata',
    description:
      'Returns JSON status from the Glama proxy (model, timestamp, readiness). Use for monitoring hooks.',
    href: '/test/chat/api/health',
    cta: 'View JSON',
    target: '_blank',
    status: { url: '/test/chat/api/health' }
  },
  {
    chip: 'Agents',
    title: 'Multi-agent smoke panel',
    description:
      'Mirrors the original node-1 multi-agent console for demonstrating saved sessions and crew selection.',
    href: '/test/agents',
    cta: 'Launch agents demo',
    status: { url: '/test/agents' }
  },
  {
    chip: 'Vision',
    title: 'Detects playground',
    description:
      'Upload frames or grab stills to run prompt presets against the GLAMA vision models and compare outputs.',
    href: '/test/detects',
    cta: 'Inspect detects UI',
    status: { url: '/test/detects' }
  },
  {
    chip: 'Vision API',
    title: 'Detects API health',
    description: 'Live health probe for the detects backend served via dev-host, ideal for automation checks.',
    href: '/test/detects/api/health',
    cta: 'View JSON',
    target: '_blank',
    status: { url: '/test/detects/api/health' }
  },
  {
    chip: 'Voice',
    title: 'Vaja TTS bench',
    description: 'Lightweight surface for piping sample scripts through Vaja and validating stream + download flow.',
    href: '/test/vaja',
    cta: 'Open Vaja UI',
    status: { url: '/test/vaja' }
  },
  {
    chip: 'Voice API',
    title: 'Vaja health endpoint',
    description: 'Checks the Vaja proxy so automations know when the voice stack is warmed up.',
    href: '/test/vaja/api/health',
    cta: 'View JSON',
    target: '_blank',
    status: { url: '/test/vaja/api/health' }
  },
  {
    chip: 'Docs',
    title: 'Test routing notes',
    description: 'Reference for how /test paths map to Caddy + systemd services. Perfect for onboarding and mirroring.',
    href: 'https://idc1.surf-thailand.com/tony',
    cta: 'node-1 panel',
    target: '_blank',
    status: { state: 'idle', label: 'External' }
  }
];

const toAbsoluteUrl = (href?: string) => {
  if (!href) return '';
  try {
    return new URL(href, window.location.origin).href;
  } catch {
    return href;
  }
};

const grid = document.getElementById('test-grid');
if (grid) {
  grid.innerHTML = cards
    .map(
      ({ chip, title, description, href, cta = 'Open', target }, index) => `
        <article class="card" data-card-index="${index}">
          <div class="card-meta">
            <span class="chip">${chip}</span>
            <span class="status-indicator" data-state="pending" data-role="status">
              <span class="status-dot"></span>
              <span class="status-label">Checking…</span>
            </span>
          </div>
          <h2>${title}</h2>
          <p>${description}</p>
          ${
            href
              ? `<p class="test-url">${toAbsoluteUrl(href)}</p><a href="${href}" ${
                  target ? `target="${target}" rel="noreferrer"` : ''
                }>${cta}</a>`
              : ''
          }
        </article>`
    )
    .join('');
}

const setIndicator = (el: HTMLElement | null | undefined, state: StatusState, label: string) => {
  if (!el) return;
  el.dataset.state = state;
  const labelEl = el.querySelector('.status-label');
  if (labelEl) {
    labelEl.textContent = label;
  }
};

const checkStatus = async (card: CardConfig, indicatorEl: HTMLElement | null) => {
  if (!indicatorEl) return;
  const statusConfig = card.status || {};
  if (statusConfig.state) {
    setIndicator(indicatorEl, statusConfig.state, statusConfig.label || 'External');
    return;
  }
  const statusUrl = statusConfig.url || card.href;
  if (!statusUrl) {
    setIndicator(indicatorEl, 'idle', 'Unknown');
    return;
  }
  const requestUrl = toAbsoluteUrl(statusUrl);
  try {
    const response = await fetch(requestUrl, { cache: 'no-store' });
    if (response.ok) {
      setIndicator(indicatorEl, 'ok', 'Online');
    } else {
      setIndicator(indicatorEl, 'error', `HTTP ${response.status}`);
    }
  } catch {
    setIndicator(indicatorEl, 'error', 'Unavailable');
  }
};

requestAnimationFrame(() => {
  cards.forEach((card, index) => {
    const cardEl = grid?.querySelector<HTMLElement>(`[data-card-index="${index}"]`);
    const indicatorEl = cardEl?.querySelector<HTMLElement>('[data-role="status"]');
    void checkStatus(card, indicatorEl || null);
  });
});

type Provider = {
  name: string;
  base_url: string;
  capabilities_path?: string;
  capabilities_updated_at?: string;
  default_tools?: string[];
  health?: { status?: string; detail?: string };
};

const providersBody = document.getElementById('providers-body') as HTMLElement | null;
const refreshBtn = document.getElementById('providers-refresh') as HTMLButtonElement | null;

const formatTools = (tools?: string[]) =>
  tools?.length ? tools.map((tool) => `<span class="tool-chip">${tool}</span>`).join('') : '<span class="tool-chip" style="opacity:0.6">No default tools</span>';

const healthState = (health?: Provider['health']) => {
  if (!health) return { state: 'idle' as StatusState, label: 'Unknown' };
  const label =
    health.detail && typeof health.detail === 'string'
      ? health.detail.slice(0, 40)
      : health.status === 'ok'
        ? 'Online'
        : 'Error';
  return { state: health.status === 'ok' ? ('ok' as StatusState) : ('error' as StatusState), label };
};

const formatUpdatedAt = (iso?: string) => {
  if (!iso) return 'never';
  const date = new Date(iso);
  return Number.isNaN(date.valueOf()) ? iso : date.toLocaleString();
};

const buildProviderCards = (providers: Provider[]) => {
  if (!providersBody) return;
  if (!providers.length) {
    providersBody.dataset.state = 'empty';
    providersBody.dataset.message = 'No providers registered.';
    providersBody.innerHTML = '';
    return;
  }
  providersBody.dataset.state = '';
  providersBody.dataset.message = '';
  providersBody.innerHTML = `
    <div class="providers-grid">
      ${providers
        .map((provider) => {
          const { state, label } = healthState(provider.health);
          return `
            <article class="provider-card">
              <div class="card-meta">
                <h3>${provider.name}</h3>
                <span class="status-indicator" data-state="${state}">
                  <span class="status-dot"></span>
                  <span class="status-label">${label}</span>
                </span>
              </div>
              <p class="provider-url">${provider.base_url}</p>
              <p class="test-url">Capabilities: ${provider.capabilities_path || '—'}</p>
              <p class="test-url">Updated: ${formatUpdatedAt(provider.capabilities_updated_at)}</p>
              <div class="tool-row">${formatTools(provider.default_tools)}</div>
            </article>
          `;
        })
        .join('')}
    </div>
  `;
};

const providersEndpoint = '/test/mcp0/providers';

const loadProviders = async (refresh = false) => {
  if (!providersBody || !refreshBtn) return;
  providersBody.dataset.state = 'loading';
  providersBody.dataset.message = 'Loading providers…';
  refreshBtn.disabled = true;
  try {
    const url = `${providersEndpoint}${refresh ? '?refresh=true' : ''}`;
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = (await response.json()) as Provider[];
    buildProviderCards(data);
  } catch (error) {
    providersBody.dataset.state = 'error';
    providersBody.dataset.message = `Failed to load providers (${(error as Error).message})`;
    providersBody.innerHTML = '';
  } finally {
    refreshBtn.disabled = false;
  }
};

refreshBtn?.addEventListener('click', () => {
  void loadProviders(true);
});

void loadProviders();
