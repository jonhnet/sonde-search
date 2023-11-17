	hs.graphicsDir = '/assets/highslide/graphics/';
	hs.showCredits = false;
	hs.transitions = ['expand', 'crossfade'];
	hs.restoreCursor = null;
	hs.lang.restoreTitle = 'Click for large image';
	hs.captionOverlay.fade = 0;

	// Add the slideshow providing the controlbar and the thumbstrip
	hs.addSlideshow({
		slideshowGroup: 'medium',
		interval: 5000,
		repeat: true,
		useControls: true,
		overlayOptions: {
			position: 'bottom right',
			offsetY: 50
		},
		thumbstrip: {
			position: 'bottom',
			mode: 'horizontal',
			relativeTo: 'expander',
			offsetY: 60,
			width: '400px'
		}
	});

	// Options for the in-page items
	var inPageOptions = {
		slideshowGroup: 'medium',
		outlineType: null,
		allowSizeReduction: true,
		wrapperClassName: 'in-page controls-in-heading zoomin',
		useBox: true,
		width: 400,
		height: 450,
		targetX: 'gallery-area 10px',
		targetY: 'gallery-area 10px',
		captionEval: 'this.a.title'
	};


	// Open the first thumb on page load
	hs.addEventListener(window, 'load', function() {
		document.getElementById('thumb1').onclick();
	});

	// Under no circumstances should the static popup be closed
	hs.Expander.prototype.onBeforeClose = function() {
		if (/in-page/.test(this.wrapper.className))	return false;
	}
	// ... nor dragged
	hs.Expander.prototype.onDrag = function() {
		if (/in-page/.test(this.wrapper.className))	return false;
	}

	// Keep the position after window resize
    hs.addEventListener(window, 'resize', function() {
		var i, exp;
		hs.getPageSize();

		for (i = 0; i < hs.expanders.length; i++) {
			exp = hs.expanders[i];
			if (exp) {
				var x = exp.x,
					y = exp.y;

				// get new thumb positions
				exp.tpos = hs.getPosition(exp.el);
				x.calcThumb();
				y.calcThumb();

				// calculate new popup position
		 		x.pos = x.tpos - x.cb + x.tb;
				x.scroll = hs.page.scrollLeft;
				x.clientSize = hs.page.width;
				y.pos = y.tpos - y.cb + y.tb;
				y.scroll = hs.page.scrollTop;
				y.clientSize = hs.page.height;
				exp.justify(x, true);
				exp.justify(y, true);

				// set new left and top to wrapper and outline
				exp.moveTo(x.pos, y.pos);
			}
		}
	});
	
	// Dynamic dimmer zIndex mod:
hs.dim = function(exp) {
	if (!hs.dimmer) {
		hs.dimmer = hs.createElement ('div',
			{
				className: 'highslide-dimming highslide-viewport-size',
				owner: '',
				onclick: function() {
					if (hs.fireEvent(hs, 'onDimmerClick')) hs.close();
				}
			}, {
                visibility: 'visible',
				opacity: 0
			}, hs.container, true);
	}
	hs.dimmer.style.zIndex = exp.wrapper.style.zIndex - 2;
	hs.dimmer.style.display = '';
	hs.dimmer.owner += '|'+ exp.key;
	if (hs.geckoMac && hs.dimmingGeckoFix)
		hs.setStyles(hs.dimmer, {
			background: 'url('+ hs.graphicsDir + 'geckodimmer.png)',
			opacity: 1
		});
	else
		hs.animate(hs.dimmer, { opacity: exp.dimmingOpacity }, hs.dimmingDuration);
};

	// Open large image on image click
	hs.Expander.prototype.onImageClick = function() {
          if (/in-page/.test(this.wrapper.className))
		   {
             stopSlideshowAndExpand(this.content, hs.extend({src: this.content.src, captionText: this.thumb.alt }, largeImage));
             return false;
          }
       }
	
	// Options for large images
	var largeImage = {
		slideshowGroup: 'large',
		outlineType: 'drop-shadow',
		allowSizeReduction: false,
		align: 'center',
		dimmingOpacity: 0.8,
		wrapperClassName: 'zoomout'
	}

	// Closebutton for large images
	hs.registerOverlay({
		html: '<div class="closebutton" onclick="return hs.close(this)" title="Close"></div>',
		position: 'top right',
		fade: 2,
		slideshowGroup: 'large'
	});
	
	// Stop slideshow when viewing large image
	function stopSlideshowAndExpand(element, config) {
        var exp = hs.getExpander(element);
        if (exp.slideshow) exp.slideshow.pause();
        return hs.expand(element, config);
    }
