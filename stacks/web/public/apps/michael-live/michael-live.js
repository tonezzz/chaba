// Michael Live — full layout page
class MichaelLivePage extends MichaelFamilyApp {}

document.addEventListener('DOMContentLoaded', () => {
    new MichaelLivePage({
        containerId: 'app',
        pageConfig: 'ssot.ui.michael-live.yml'
    });
});
