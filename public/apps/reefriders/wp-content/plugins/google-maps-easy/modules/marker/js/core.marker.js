// Markers
function gmpCanUseAdvancedMarkers() {
  return !!(window.google && google.maps && google.maps.marker && google.maps.marker.AdvancedMarkerElement);
}
function gmpGetMarkerMapInstance(map) {
  return map && typeof map.getRawMapInstance == 'function' ? map.getRawMapInstance() : null;
}
function gmpNormalizeMarkerPosition(position) {
  if (!position) {
    return position;
  }
  if (typeof position.lat === 'function' && typeof position.lng === 'function') {
    return position;
  }
  if (typeof position.lat !== 'undefined' && typeof position.lng !== 'undefined') {
    return new google.maps.LatLng(position.lat, position.lng);
  }
  return position;
}
function gmpCreateAdvancedMarkerContent(icon) {
  if (!icon || typeof icon !== 'string') {
    return null;
  }
  var markerContent = document.createElement('img');

  markerContent.src = icon;
  markerContent.alt = '';
  markerContent.className = 'gmp-advanced-marker-icon';
  markerContent.style.maxWidth = 'none';
  markerContent.style.position = 'absolute';
  markerContent.style.transform = 'translate(-50%, -100%)';
  markerContent.title = '';

  return markerContent;
}
function gmpPatchAdvancedMarker(marker) {
  if (!marker || marker._gmpPatched) {
    return marker;
  }
  marker._gmpPatched = true;
  marker._gmpNativeSetMap = typeof marker.setMap === 'function' ? marker.setMap.bind(marker) : null;
  marker._gmpNativeGetMap = typeof marker.getMap === 'function' ? marker.getMap.bind(marker) : null;
  marker._gmpVisible = marker._gmpNativeGetMap ? marker._gmpNativeGetMap() !== null : marker.map !== null;
  marker._gmpIcon = marker.content && marker.content.tagName === 'IMG' ? marker.content.src : null;
  marker.getPosition = function () {
    return gmpNormalizeMarkerPosition(this.position);
  };
  marker.setPosition = function (position) {
    this.position = gmpNormalizeMarkerPosition(position);
  };
  marker.getMap = function () {
    return this._gmpNativeGetMap ? this._gmpNativeGetMap() : this.map || null;
  };
  marker.setMap = function (map) {
    if (this._gmpNativeSetMap) {
      this._gmpNativeSetMap(map);
    } else {
      this.map = map;
    }
    this._gmpVisible = map !== null;
  };
  marker.getVisible = function () {
    return this._gmpVisible;
  };
  marker.setVisible = function (state) {
    this._gmpVisible = !!state;
    if (this._gmpNativeSetMap) {
      this._gmpNativeSetMap(state ? this._gmpOwnerMap : null);
    } else {
      this.map = state ? this._gmpOwnerMap : null;
    }
  };
  marker.getIcon = function () {
    return this._gmpIcon;
  };
  marker.setIcon = function (icon) {
    this._gmpIcon = icon;
    this.content = gmpCreateAdvancedMarkerContent(icon);
  };
  marker.setTitle = function (title) {
    this.title = title;
    if (this.content) {
      this.content.title = '';
      this.content.setAttribute('aria-label', title || '');
    }
  };
  return marker;
}
function gmpGoogleMarker(map, params) {
  this._map = map;
  this._markerObj = null;
  this._useAdvancedMarker = false;
  this._hoverInfoWndTimeout = null;
  var defaults = {
    // Empty for now
  };
  if (!params.position && params.coord_x && params.coord_y) {
    params.position = new google.maps.LatLng(params.coord_x, params.coord_y);
  }
  this._markerParams = jQuery.extend({}, defaults, params);
  this._markerParams.map = this._map.getRawMapInstance();
  //this._id = params.id ? params.id : 0;
  this._infoWindow = null;
  this._infoWndOpened = false;
  this._infoWndWasInited = false;
  this._infoWndDirectionsBtn = false;
  this._infoWndPrintBtn = false;
  this._mapDragScroll = {
    scrollwheel: null,
  };
  this.init();
}
gmpGoogleMarker.prototype.infoWndOpened = function () {
  return this._infoWndOpened;
};
gmpGoogleMarker.prototype._clearHoverInfoWndTimeout = function () {
  if (this._hoverInfoWndTimeout) {
    clearTimeout(this._hoverInfoWndTimeout);
    this._hoverInfoWndTimeout = null;
  }
};
gmpGoogleMarker.prototype._canUseAdvancedMarker = function () {
  var mapId = this._map.getParam('mapId');

  return gmpCanUseAdvancedMarkers() && !!this._map.getRawMapInstance() && !!mapId;
};
gmpGoogleMarker.prototype._prepareAdvancedMarkerParams = function (params) {
  var markerParams = {
    map: gmpGetMarkerMapInstance(this._map),
    position: gmpNormalizeMarkerPosition(params.position),
    gmpDraggable: !!params.draggable,
  };

  if (params.zIndex) {
    markerParams.zIndex = params.zIndex;
  }
  if (typeof params.gmpClickable !== 'undefined') {
    markerParams.gmpClickable = !!params.gmpClickable;
  }
  if (typeof params.collisionBehavior !== 'undefined') {
    markerParams.collisionBehavior = params.collisionBehavior;
  }
  markerParams.content = gmpCreateAdvancedMarkerContent(params.icon);

  return markerParams;
};
gmpGoogleMarker.prototype._bindMarkerListener = function (eventName, callback) {
  if (!this._markerObj) {
    return;
  }
  if (this._useAdvancedMarker) {
    if (eventName === 'click') {
      eventName = 'gmp-click';
    }
    if ((eventName === 'mouseover' || eventName === 'mouseout') && this._markerObj.content && typeof this._markerObj.content.addEventListener === 'function') {
      this._markerObj.content.addEventListener(eventName, callback);
      return;
    }
  }
  if (typeof this._markerObj.addListener == 'function') {
    this._markerObj.addListener(eventName, callback);
  } else {
    google.maps.event.addListener(this._markerObj, eventName, callback);
  }
};
gmpGoogleMarker.prototype._openInfoWindow = function () {
  if (this._useAdvancedMarker) {
    this._infoWindow.open({
      map: this._map.getRawMapInstance(),
      anchor: this._markerObj,
    });
  } else {
    this._infoWindow.open(this._map.getRawMapInstance(), this._markerObj);
  }
};
gmpGoogleMarker.prototype.init = function () {
  var markerParamsForCreate = this._markerParams,
    openInfoWndEvent = 'click',
    closeInfoWndEvent = '',
    openLinkEvent = 'click';

  if (parseInt(this._map._mapParams.hide_marker_tooltip)) {
    this._markerParams.marker_title = this._markerParams.title;
    delete markerParamsForCreate.title;
  }
  if (this._canUseAdvancedMarker()) {
    this._markerObj = gmpPatchAdvancedMarker(new google.maps.marker.AdvancedMarkerElement(this._prepareAdvancedMarkerParams(markerParamsForCreate)));
    this._markerObj._gmpOwnerMap = this._map.getRawMapInstance();
    this._markerObj.params = this._markerParams.params || {};
    this._markerObj.marker_group_id = this._markerParams.marker_group_id || 0;
    this._markerObj.draggable = !!this._markerParams.draggable;
    this._useAdvancedMarker = true;
  } else {
    this._markerObj = new google.maps.Marker(markerParamsForCreate);
    if (typeof this._markerObj.setTitle === 'function') {
      this._markerObj.setTitle('');
    }
  }
  if (this._markerParams.dragend) {
    this._bindMarkerListener('dragend', jQuery.proxy(this._markerParams.dragend, this));
  }
  if (this._markerParams.click) {
    this._bindMarkerListener('click', jQuery.proxy(this._markerParams.click, this));
  }
  if (this._markerParams.params && !(window.ontouchstart === null || navigator.msMaxTouchPoints)) {
    if (parseInt(this._markerParams.params.description_mouse_hover)) {
      openInfoWndEvent = 'mouseover';
      if (parseInt(this._markerParams.params.description_mouse_leave)) {
        closeInfoWndEvent = 'mouseout';
      }
    }
  }
  this._bindMarkerListener(
    openInfoWndEvent,
    jQuery.proxy(function () {
      if (this._markerParams.params && !parseInt(this._markerParams.params.description_mouse_hover) && parseInt(this._markerParams.params.marker_link)) {
        return;
      } else if (openInfoWndEvent === 'mouseover') {
        this._clearHoverInfoWndTimeout();
        this._hoverInfoWndTimeout = setTimeout(
          jQuery.proxy(function () {
            this.showInfoWnd();
            this._hoverInfoWndTimeout = null;
          }, this),
          500
        );
      } else {
        this.showInfoWnd();
      }
      jQuery(document).trigger('gmapAfterMarkerClick', this);
    }, this)
  );
  if (closeInfoWndEvent) {
    this._bindMarkerListener(
      closeInfoWndEvent,
      jQuery.proxy(function () {
        var self = this,
          infoWndDiv = jQuery('.gm-style-iw').parent(),
          timeout = 300;

        self._clearHoverInfoWndTimeout();

        infoWndDiv.on('mouseover', function () {
          // Mouse is on infowindow content
          infoWndDiv.addClass('hovering');
        });
        infoWndDiv.on('mouseleave', function () {
          // Hide infowindow after mouse have left infowindow content
          setTimeout(function () {
            self.hideInfoWnd();
          }, timeout);
        });
        setTimeout(function () {
          // Hide infowindow if mouse is not on infowindow content
          if (!infoWndDiv.hasClass('hovering')) {
            self.hideInfoWnd();
          }
        }, timeout);
      }, this)
    );
  }
  if (this._markerParams.params && parseInt(this._markerParams.params.marker_link)) {
    this._bindMarkerListener(
      openLinkEvent,
      jQuery.proxy(function () {
        var isLink = /http/gi,
          markerLink = !this._markerParams.params.marker_link_src.match(isLink) ? 'http://' + this._markerParams.params.marker_link_src : this._markerParams.params.marker_link_src;

        if (parseInt(this._markerParams.params.marker_link_new_wnd)) {
          window.open(markerLink, '_blank');
        } else {
          location.href = markerLink;
        }
      }, this)
    );
  }
};
gmpGoogleMarker.prototype.showInfoWnd = function (forceUpdateInfoWnd, forceShow) {
  var allShapes = this._map.getAllShapes();
  if (allShapes && allShapes.length) {
    for (var i = 0; i < allShapes.length; i++) {
      if (allShapes[i]._infoWndOpened) allShapes[i].hideInfoWnd();
    }
  }
  if (!this._infoWndWasInited || forceUpdateInfoWnd) {
    this._updateInfoWndContent();
    this._infoWndWasInited = true;
  }
  if (this._infoWindow && !this._infoWndOpened) {
    var allMapMArkers = this._map.getAllMarkers();
    // Google Maps Javascript API v3 allows to open several infowindows on map
    if (allMapMArkers && allMapMArkers.length > 1 && !forceShow) {
      for (var i = 0; i < allMapMArkers.length; i++) {
        allMapMArkers[i].hideInfoWnd();
      }
    }
    if (parseInt(this.getMap().getParam('center_on_cur_marker_infownd')) && !GMP_DATA.isAdmin) {
      this.getMap().setCenter(this.getMarkerParam('position'));
    }
    if (this._map.getParam('marker_infownd_type') == 'slide' && typeof this.showInfoWndSlide == 'function') {
      this.showInfoWndSlide();
    } else {
      this._openInfoWindow();
    }
    this._infoWndOpened = true;
  }
};
gmpGoogleMarker.prototype.hideInfoWnd = function () {
  this._clearHoverInfoWndTimeout();
  if (this._infoWindow && this._infoWndOpened) {
    this._infoWindow.close();
    this._infoWndOpened = false;

    var googleMap = this._map.getRawMapInstance();
    googleMap.setOptions({ scrollwheel: this._mapDragScroll.scrollwheel });

    jQuery(document).trigger('gmapAfterHideInfoWnd', this);
  }
};
gmpGoogleMarker.prototype.getRawMarkerInstance = function () {
  return this._markerObj;
};
gmpGoogleMarker.prototype.getRawMarkerParams = function () {
  return this._markerParams;
};
gmpGoogleMarker.prototype.getIcon = function () {
  return this._markerObj.getIcon();
};
gmpGoogleMarker.prototype.setIcon = function (iconPath) {
  this._markerObj.setIcon(iconPath);
  this._markerParams.icon = iconPath;
};
gmpGoogleMarker.prototype.setTitle = function (title, noRefresh) {
  if (!parseInt(this._map._mapParams.hide_marker_tooltip)) this._markerObj.setTitle(title);
  this._markerParams.title = title;
  if (!noRefresh) this._updateInfoWndContent();
};
gmpGoogleMarker.prototype.getTitle = function () {
  return typeof this._markerParams.title != 'undefined' ? this._markerParams.title : this._markerParams.marker_title;
};
gmpGoogleMarker.prototype.getPosition = function () {
  return this._markerObj.getPosition();
};
gmpGoogleMarker.prototype.setPosition = function (lat, lng) {
  var position = new google.maps.LatLng(lat, lng);
  this._markerObj.setPosition(position);
  this._markerParams.position = position;
};
gmpGoogleMarker.prototype.lat = function () {
  return this.getPosition().lat();
};
gmpGoogleMarker.prototype.lng = function (lng) {
  return this.getPosition().lng();
};
gmpGoogleMarker.prototype.setId = function (id) {
  this._markerParams.id = id;
};
gmpGoogleMarker.prototype.getId = function () {
  return this._markerParams.id;
};
gmpGoogleMarker.prototype.setDescription = function (description, noRefresh) {
  this._markerParams.description = description;
  if (!noRefresh) this._updateInfoWndContent();
  if (this._markerParams.params && parseInt(this._markerParams.params.show_description)) {
    this.showInfoWnd(false, true);
  }
};
gmpGoogleMarker.prototype.getDescription = function () {
  return this._markerParams.description;
};
gmpGoogleMarker.prototype._setTitleColor = function (titleDiv) {
  var titleColor = this._map.getParam('marker_title_color');

  if (titleColor && titleColor != '') {
    titleDiv.css({
      color: titleColor,
    });
  }
  return titleDiv;
};
gmpGoogleMarker.prototype._setTitleSize = function (titleDiv) {
  var titleSize = this._map.getParam('marker_title_size'),
    titleSizeUnits = this._map.getParam('marker_title_size_units');

  if (titleSize && titleSizeUnits && titleSize != '') {
    titleDiv.css({
      'font-size': titleSize + titleSizeUnits,
      'line-height': +titleSize + 5 + titleSizeUnits,
    });
  }
  return titleDiv;
};
gmpGoogleMarker.prototype._setDescSize = function (descDiv) {
  var descSize = this._map.getParam('marker_desc_size'),
    descSizeUnits = this._map.getParam('marker_desc_size_units');

  if (descSize && descSizeUnits && descSize != '') {
    descDiv.css({
      'font-size': descSize + descSizeUnits,
      'line-height': parseInt(descSize) + 5 + descSizeUnits,
    });
  }
  return descDiv;
};
gmpGoogleMarker.prototype._updateInfoWndContent = function () {
  var contentStr = jQuery('<div/>', {}),
    description = this._markerParams.description ? this._markerParams.description.replace(/\n/g, '<br/>') : false,
    title = this._markerParams.title ? this._markerParams.title : false;

  if (parseInt(this._map._mapParams.hide_marker_tooltip) && !GMP_DATA.isAdmin) {
    title = this._markerParams.marker_title ? this._markerParams.marker_title : false;
  }
  if (title) {
    var titleDiv = jQuery('<div/>', {}).addClass('gmpInfoWindowtitle').html(title);

    titleDiv = this._setTitleColor(titleDiv);
    titleDiv = this._setTitleSize(titleDiv);
    contentStr.append(titleDiv);

    if (this._infoWndDirectionsBtn) {
      this._infoWndDirectionsBtn.insertAfter(contentStr.find('.gmpInfoWindowtitle'));
    }
    if (this._infoWndPrintBtn) {
      this._infoWndPrintBtn.insertAfter(contentStr.find('.gmpInfoWindowtitle'));
    }
  }
  if (description) {
    var descDiv = jQuery('<div/>', {}).addClass('egm-marker-iw').html(description);

    descDiv = this._setDescSize(descDiv);
    contentStr.append(descDiv);

    // Check scripts in description, and execute them if they are there
    var $scripts = contentStr.find('script');
    if ($scripts && $scripts.length) {
      $scripts.each(function () {
        var scriptSrc = jQuery(this).attr('src');
        if (scriptSrc && scriptSrc != '') {
          jQuery.getScript(scriptSrc);
        }
      });
    }
  }
  this._setInfoWndContent(contentStr);
};
/**
 * Just mark it as closed
 */
gmpGoogleMarker.prototype._setInfoWndClosed = function () {
  this._infoWndOpened = false;
  jQuery(document).trigger('gmapAfterHideInfoWnd', this);
};
gmpGoogleMarker.prototype._setInfoWndContent = function (newContentHtmlObj) {
  var self = this,
    map = this.getMap();

  if (!this._infoWindow) {
    var mapWidth = GMP_DATA.isAdmin ? jQuery('#gmpMapPreview').width() : jQuery('#' + map.getViewHtmlId()).width(),
      infoWndType = map.getParam('marker_infownd_type'),
      infoWndWidth = map.getParam('marker_infownd_width_units') == 'px' ? map.getParam('marker_infownd_width') : mapWidth - 20,
      infoWndHeight = map.getParam('marker_infownd_height_units') == 'px' ? map.getParam('marker_infownd_height') + 'px' : false,
      maxWndWidth = mapWidth * 0.6,
      infoWndParams = { maxWidth: infoWndWidth < maxWndWidth ? infoWndWidth : maxWndWidth };

    switch (infoWndType) {
      case 'rounded_edges':
        infoWndParams.pixelOffset = new google.maps.Size(0, 10);
        break;
      default:
        break;
    }

    //add disableAutoPan property if description_mouse_leave is true
    /*if(this._markerParams.params && this._markerParams.params.description_mouse_leave)
			infoWndParams['disableAutoPan'] = true;*/

    this._infoWindow = new google.maps.InfoWindow(infoWndParams);

    google.maps.event.addListener(this._infoWindow, 'domready', function () {
      changeInfoWndType(map);
      changeInfoWndBgColor(map);
      // check if tooltip text has "Gallery by Supsystic"
      if (this.content && this.content.innerHTML && this.content.innerHTML.indexOf && this.content.innerHTML.indexOf('id="grid-gallery-') != -1) {
        jQuery(document).trigger('ggFirInitialize');
      }
    });
    google.maps.event.addListener(this._infoWindow, 'closeclick', function () {
      self._setInfoWndClosed();
    });
  }
  if (infoWndHeight) {
    newContentHtmlObj.css('cssText', 'max-height: ' + infoWndHeight + ';');
  }

  // Fix bug in FF - scroll on infowindow content changes map zoom
  var scrollwheel = map.get('scrollwheel'),
    googleMap = map.getRawMapInstance();

  //Save scrollwheel setting to container before rewrite it.
  this._mapDragScroll.scrollwheel = scrollwheel;

  newContentHtmlObj.hover(
    function () {
      googleMap.setOptions({ scrollwheel: false });
    },
    function () {
      googleMap.setOptions({ scrollwheel: scrollwheel });
    }
  );
  this._infoWindow.setContent(newContentHtmlObj[0]);
};
gmpGoogleMarker.prototype.removeFromMap = function () {
  this.getRawMarkerInstance().setMap(null);
};
gmpGoogleMarker.prototype.setMarkerParams = function (params) {
  this._markerParams = params;
  return this;
};
gmpGoogleMarker.prototype.setMarkerParam = function (key, value) {
  this._markerParams[key] = value;
  return this;
};
gmpGoogleMarker.prototype.getMarkerParam = function (key) {
  return this._markerParams[key];
};
gmpGoogleMarker.prototype.setMap = function (map) {
  if (this._useAdvancedMarker && map) {
    this._markerObj._gmpOwnerMap = map;
  }
  this.getRawMarkerInstance().setMap(map);
};
gmpGoogleMarker.prototype.getMap = function () {
  return this._map;
};
gmpGoogleMarker.prototype.setVisible = function (state) {
  this.getRawMarkerInstance().setVisible(state);
};
gmpGoogleMarker.prototype.getVisible = function () {
  return this.getRawMarkerInstance().getVisible();
};
// Common functions
function _gmpPrepareMarkersList(markers, params) {
  params = params || {};
  if (markers) {
    for (var i = 0; i < markers.length; i++) {
      markers[i].coord_x = parseFloat(markers[i].coord_x);
      markers[i].coord_y = parseFloat(markers[i].coord_y);
      markers[i].icon = markers[i].icon_data.path;
      if (params.dragend) {
        markers[i].draggable = true;
        markers[i].dragend = params.dragend;
      }
    }
  }
  return markers;
}

window.gmpGoogleMarker = gmpGoogleMarker;
