class CourseManager {
  constructor(options = {}) {
    this.stateManager = options.stateManager;
    this.renderer = options.renderer;
    this.simulation = options.simulation;
    this.getCourseId = options.getCourseId;
    this.setCourseId = options.setCourseId;
    this.getCourseData = options.getCourseData;
    this.setCourseData = options.setCourseData;
    this.getRenderer = options.getRenderer;
    this.setRenderer = options.setRenderer;
    this.getSimulation = options.getSimulation;
    this.onRender = options.onRender;
    this.onLoadOverrides = options.onLoadOverrides;
    this.onLoadServerState = options.onLoadServerState;
    this.onThemeLoad = options.onThemeLoad;
    this.onShowMsg = options.onShowMsg;
  }

  updateUrlCourse() {
    const courseId = this.getCourseId();
    const url = new URL(window.location.href);
    url.searchParams.set('course', courseId);
    window.history.replaceState({}, '', url);
  }

  async populateCourseList() {
    try {
      const r = await fetch('api/list.php');
      if (!r.ok) return;
      const list = await r.json();
      const sel = document.getElementById('course-select');
      if (!sel) return;
      sel.innerHTML = '<option value="">Load course...</option>';
      for (const c of list) {
        const label = c.name + (c.saved ? ' (saved)' : '');
        const opt = document.createElement('option');
        opt.value = c.name;
        opt.textContent = label;
        sel.appendChild(opt);
      }
      sel.value = '';
    } catch (e) { console.warn('course list failed', e); }
  }

  async loadCourseYaml(id) {
    const r = await fetch(`courses/${id}.yml`, { cache: 'no-store' });
    if (!r.ok) throw new Error(`course not found: ${r.status}`);
    return jsyaml.load(await r.text());
  }

  async loadCourse(id) {
    if (!id || !/^[a-zA-Z0-9_-]+$/.test(id)) { 
      this.onShowMsg('invalid course name'); 
      return; 
    }
    
    if (this.simulation) this.simulation.stop();
    
    try {
      const courseData = await this.loadCourseYaml(id);
      this.setCourseData(courseData);
    } catch (e) {
      console.warn(`no YAML for ${id}; keeping current base`, e);
    }
    
    this.setCourseId(id);
    if (this.onLoadOverrides) this.onLoadOverrides();
    if (this.onLoadServerState) await this.onLoadServerState();
    
    document.getElementById('course-name').value = id;
    this.updateUrlCourse();
    
    let ThemeClass = DefaultTheme;
    if (this.onThemeLoad) {
      try { ThemeClass = await this.onThemeLoad(); } catch (e) { console.warn('theme load failed', e); }
    }
    
    let renderer = this.getRenderer();
    if (!renderer) {
      renderer = new CourseRenderer(window.map, { roundDist: window.ROUND_DIST || 25, theme: new ThemeClass() });
      this.setRenderer(renderer);
    }
    renderer.hidden = this.stateManager.getHidden();
    
    if (this.onRender) this.onRender(true);
    if (this.simulation) this.simulation.initRacers();
    
    if (renderer.theme && renderer.theme.installChrome) {
      renderer.theme.installChrome(this.getCourseData());
    }
    
    await this.populateCourseList();
    this.onShowMsg('Loaded ' + id);
  }

  async saveCourse(name) {
    name = (name || '').trim();
    if (!name) name = this.getCourseId();
    if (!/^[a-zA-Z0-9_-]+$/.test(name)) { 
      this.onShowMsg('invalid course name'); 
      return; 
    }
    
    const currentState = this.stateManager.getState();
    const payload = { course: name, overrides: currentState.overrides, hidden: [...currentState.hidden] };
    
    try {
      const r = await fetch('api/save.php', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await r.json().catch(() => ({}));
      if (r.ok && data.ok) {
        this.setCourseId(name);
        this.stateManager.setCourseId(name);
        try { localStorage.setItem(this.stateManager.getStorageKey(), JSON.stringify(currentState.overrides)); } catch (e) {}
        document.getElementById('course-name').value = name;
        this.updateUrlCourse();
        await this.populateCourseList();
        this.onShowMsg('Saved ' + name);
      } else {
        this.onShowMsg(data.error || 'save failed');
      }
    } catch (e) {
      console.warn('save failed', e);
      this.onShowMsg('save error');
    }
  }

  setupCourseControls() {
    const nameInput = document.getElementById('course-name');
    const sel = document.getElementById('course-select');
    if (nameInput) nameInput.value = this.getCourseId();
    this.populateCourseList();
    document.getElementById('btn-save').onclick = () => this.saveCourse(nameInput ? nameInput.value : '');
    document.getElementById('btn-load').onclick = () => { if (sel && sel.value) this.loadCourse(sel.value); };
  }
}