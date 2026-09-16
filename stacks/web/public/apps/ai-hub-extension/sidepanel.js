const promptInput = document.getElementById('prompt');
const sendBtn = document.getElementById('send');
const responsesDiv = document.getElementById('responses');
const checkboxes = document.querySelectorAll('.targets input');

function selectedTargets() {
  return Array.from(checkboxes).filter(c => c.checked).map(c => c.value);
}

function appendResponse(site, text) {
  const div = document.createElement('div');
  div.className = 'response';
  div.innerHTML = `<h3>${site}</h3><pre>${text}</pre>`;
  responsesDiv.appendChild(div);
}

sendBtn.addEventListener('click', () => {
  const text = promptInput.value.trim();
  if (!text) return;
  const targets = selectedTargets();
  chrome.runtime.sendMessage({ cmd: 'BROADCAST_PROMPT', text, targets });
});

chrome.runtime.onMessage.addListener(request => {
  if (request.cmd === 'RESPONSE') {
    appendResponse(request.site, request.text);
  }
});
