class YamlEditor {
  constructor(options = {}) {
    this.getCourseId = options.getCourseId;
    this.onShowMsg = options.onShowMsg;
    this.onActivateTab = options.onActivateTab;
    this.onLoadCourse = options.onLoadCourse;
  }

  showYamlMsg(text) {
    const el = document.getElementById('yaml-msg');
    if (el) {
      el.textContent = text;
      setTimeout(() => { if (el.textContent === text) el.textContent = ''; }, 3000);
    }
  }

  async openYamlEditor() {
    const textarea = document.getElementById('yaml-text');
    if (!textarea) return;
    const courseId = this.getCourseId();
    try {
      const r = await fetch(`courses/${courseId}.yml`, { cache: 'no-store' });
      if (!r.ok) throw new Error(`load ${r.status}`);
      textarea.value = await r.text();
    } catch (e) {
      console.warn('yaml load failed', e);
      this.showYamlMsg('Failed to load YAML');
    }
  }

  async saveYamlEditor() {
    const textarea = document.getElementById('yaml-text');
    if (!textarea) return;
    const yaml = textarea.value;
    const courseId = this.getCourseId();
    
    try {
      try { jsyaml.load(yaml); } catch (e) { 
        this.showYamlMsg('Invalid YAML: ' + e.message); 
        return; 
      }
      
      const r = await fetch('api/save-course.php', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ course: courseId, yaml })
      });
      
      const data = await r.json().catch(() => ({}));
      if (r.ok && data.ok) {
        this.showYamlMsg('Saved; reloading...');
        if (this.onLoadCourse) await this.onLoadCourse(courseId);
        if (this.onActivateTab) this.onActivateTab('course');
      } else {
        this.showYamlMsg(data.error || 'save failed');
      }
    } catch (e) {
      console.warn('yaml save failed', e);
      this.showYamlMsg('save error');
    }
  }

  setupYamlEditor() {
    const cancel = document.getElementById('btn-cancel-yaml');
    const save = document.getElementById('btn-save-yaml');
    if (cancel) cancel.onclick = () => this.onActivateTab ? this.onActivateTab('course') : null;
    if (save) save.onclick = () => this.saveYamlEditor();
  }
}