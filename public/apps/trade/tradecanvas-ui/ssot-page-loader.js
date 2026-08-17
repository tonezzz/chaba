// TradeCanvas SSOT Page Config Loader
// Resolves 4 layers: ssot.ui.yml -> ssot.ui.<family>.yml -> ssot.ui.<page>.yml -> ssot.ui.feature.*.yml

function deepMerge(base, page) {
    if (page === null || typeof page !== 'object') return page;
    if (Array.isArray(page)) return page;
    if (base === null || typeof base !== 'object' || Array.isArray(base)) base = {};
    const result = { ...base };
    for (const [key, value] of Object.entries(page)) {
        if (value !== null && typeof value === 'object' && !Array.isArray(value) &&
            result[key] !== null && typeof result[key] === 'object' && !Array.isArray(result[key])) {
            result[key] = deepMerge(result[key], value);
        } else {
            result[key] = value;
        }
    }
    return result;
}

function stripRefs(obj) {
    if (obj === null || typeof obj !== 'object') return obj;
    if (Array.isArray(obj)) return obj.map(stripRefs);
    const result = {};
    for (const [key, value] of Object.entries(obj)) {
        if (key === 'ref') continue;
        result[key] = stripRefs(value);
    }
    return result;
}

async function loadYamlFile(yaml, filename, isOptional = false) {
    try {
        const resp = await fetch(filename);
        if (!resp.ok) {
            if (isOptional) {
                console.log(`SSOT file not found (optional): ${filename}`);
                return null;
            }
            throw new Error(`${filename} not found`);
        }
        const doc = yaml.load(await resp.text());
        console.log(`Parsed ${filename}, keys:`, Object.keys(doc || {}));
        return doc;
    } catch (e) {
        if (isOptional) {
            console.log(`Optional SSOT load skipped for ${filename}:`, e.message);
            return null;
        }
        throw e;
    }
}

async function loadPageConfig() {
    const yaml = (typeof jsyaml !== 'undefined' && jsyaml.load) ? jsyaml : null;
    if (!yaml) throw new Error('js-yaml library not loaded');

    const baseDoc = await loadYamlFile(yaml, 'ssot.ui.yml');
    const pageName = (window.location.pathname.split('/').pop() || 'compare').replace('.html', '');
    const pageDoc = await loadYamlFile(yaml, `ssot.ui.${pageName}.yml`, true) || {};

    // Load family if declared
    let familyDoc = {};
    if (pageDoc.family) {
        familyDoc = await loadYamlFile(yaml, `ssot.ui.${pageDoc.family}.yml`, true) || {};
    }

    // Load feature SSOTs referenced from family and page
    const featureFiles = new Set();
    if (Array.isArray(familyDoc.features)) {
        for (const featureFile of familyDoc.features) featureFiles.add(featureFile);
    }
    if (Array.isArray(pageDoc.features)) {
        for (const featureFile of pageDoc.features) featureFiles.add(featureFile);
    }
    const featureDocs = [];
    for (const featureFile of featureFiles) {
        const featureDoc = await loadYamlFile(yaml, featureFile, true);
        if (featureDoc) featureDocs.push(featureDoc);
    }

    // Remove family/features metadata from page before merging
    const pageOnlyDoc = { ...pageDoc };
    delete pageOnlyDoc.family;
    delete pageOnlyDoc.features;

    // Merge order: base -> family -> page -> features
    let config = deepMerge(baseDoc, familyDoc);
    config = deepMerge(config, pageOnlyDoc);
    for (const feature of featureDocs) {
        config = deepMerge(config, feature);
    }

    // Preserve the resolved page id for downstream use
    config.page = config.page || {};
    config.page.id = config.page.id || pageName;

    return stripRefs(config);
}

if (typeof window !== 'undefined') {
    window.loadPageConfig = loadPageConfig;
    window.SSOTMerge = deepMerge;
    window.SSOTMerge.stripRefs = stripRefs;
    window.SSOTMerge.deepMerge = deepMerge;
}
