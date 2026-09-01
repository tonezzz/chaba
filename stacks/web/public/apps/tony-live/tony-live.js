// Tony Live — full layout page
class TonyLivePage extends TonyFamilyApp {}

document.addEventListener('DOMContentLoaded', () => {
    new TonyLivePage({
        containerId: 'app',
        pageConfig: 'ssot.ui.tony-live.yml'
    });
});
