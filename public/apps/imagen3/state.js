export const MAX_HISTORY = 12;
export const MAX_QUEUE = 5;

export const state = {
  history: [],
  queue: [],
  activeJob: null,
  currentItem: null,
  currentB64: null,
  refBase64: '',
  activeView: 'generated',
  pendingDeleteIndex: -1,
  modalItem: null,
  currentPreset: '',
  MAX_HISTORY,
  MAX_QUEUE
};
