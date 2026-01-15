const guidanceText = document.getElementById('guidanceText');
const guidanceCard = document.getElementById('guidanceCard');
const guidanceForm = document.getElementById('guidanceForm');
const customGuidanceInput = document.getElementById('customGuidance');
const statusEl = document.getElementById('status');

const GUIDANCE_KEY = 'talk_custom_guidance';

const renderStatus = (text, ok = false) => {
  statusEl.textContent = text;
  statusEl.classList.toggle('ok', ok);
};

const loadDefaultGuidance = async () => {
  const res = await fetch('/api/talk/guidance');
  if (!res.ok) {
    throw new Error('guidance_api_failed');
  }
  const data = await res.json();
  guidanceText.textContent = data.guidance || 'Guidance unavailable';
};

const loadSavedGuidance = () => {
  const saved = localStorage.getItem(GUIDANCE_KEY);
  if (saved) {
    customGuidanceInput.value = saved;
  }
};

const handleGuidanceSubmit = (event) => {
  event.preventDefault();
  const content = customGuidanceInput.value.trim();
  localStorage.setItem(GUIDANCE_KEY, content);
  renderStatus(content ? 'Custom guidance saved' : 'Cleared custom guidance', true);
};

guidanceForm.addEventListener('submit', handleGuidanceSubmit);

window.addEventListener('load', async () => {
  try {
    await loadDefaultGuidance();
    loadSavedGuidance();
    renderStatus('Ready to steer the conversation', true);
  } catch (error) {
    console.error('Talk panel init failed', error);
    renderStatus('Failed to load guidance', false);
  }
});
