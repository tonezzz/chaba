export const $ = (id) => document.getElementById(id);

export function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export function base64ToBlob(b64, mime) {
  const byteString = atob(b64);
  const ab = new ArrayBuffer(byteString.length);
  const ia = new Uint8Array(ab);
  for (let i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i);
  return new Blob([ab], { type: mime });
}

export function appendIfMissing(el, text) {
  const current = el.value.trim();
  const parts = text.split(',').map(s => s.trim()).filter(Boolean);
  if (!current) {
    el.value = parts.join(', ');
  } else {
    const existing = current.split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
    const missing = parts.filter(p => !existing.includes(p.toLowerCase()));
    if (missing.length) {
      const sep = /[,;]$/.test(current) ? ' ' : ', ';
      el.value = current + sep + missing.join(', ');
    }
  }
}
