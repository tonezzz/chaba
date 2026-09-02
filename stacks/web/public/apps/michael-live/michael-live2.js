// Michael Live 2 — compact layout page
class MichaelLive2Page extends MichaelFamilyApp {}

document.addEventListener('DOMContentLoaded', () => {
    new MichaelLive2Page({
        containerId: 'app',
        pageConfig: 'ssot.ui.michael-live2.yml'
    });
});
