document.addEventListener('DOMContentLoaded', function () {
  // Mobile menu toggle
  var toggle = document.getElementById('menu-toggle');
  var menu = document.getElementById('menu-main');
  if (toggle && menu) {
    toggle.addEventListener('click', function () {
      var open = menu.classList.toggle('open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  // Active nav item
  var cur = location.pathname.replace(/\/$/, '');
  document.querySelectorAll('#masternav a').forEach(function (a) {
    var href = a.getAttribute('href');
    if (!href || href.indexOf('javascript:') === 0) return;
    var u;
    try {
      u = new URL(href, location.href).pathname.replace(/\/$/, '');
    } catch (e) { return; }
    if (u && u === cur) {
      var li = a.closest('li');
      if (li) li.classList.add('current-menu-item');
      a.setAttribute('aria-current', 'page');
    }
  });

  // Guarded Splide init
  if (document.getElementById('slider-wrap') && typeof Splide !== 'undefined') {
    new Splide('#slider-wrap', {
      type: 'loop',
      autoplay: true,
      interval: 4000,
      pauseOnHover: true,
      arrows: true,
      pagination: true,
      speed: 800
    }).mount();
  }
});
